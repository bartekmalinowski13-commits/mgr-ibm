"""Embedding clients: gateway (OpenAI-compatible ``/v1/embeddings`` of LiteLLM) and a
deterministic hashing embedder for tests and offline development.

Per ADR-0006 the platform never calls a provider SDK directly: LiteLLM holds provider
credentials, budgets and the EU allow-list, and exposes one OpenAI-compatible API.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx
from opentelemetry import trace

DIMENSIONS = 1024
tracer = trace.get_tracer(__name__)
_TOKEN = re.compile(r"[a-z0-9µΩ]+(?:[.,][0-9]+)?", re.IGNORECASE)


class EmbeddingClient(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddings:
    """Feature-hashing bag of words + character trigrams, L2-normalised.

    Deterministic and dependency-free: cosine similarity tracks lexical overlap, which
    is enough to test retrieval plumbing and fusion. Not a semantic model.
    """

    def __init__(self, dimensions: int = DIMENSIONS, model: str = "fake-embedding") -> None:
        self.dimensions = dimensions
        self.model = model

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = [t.lower() for t in _TOKEN.findall(text)]
        features = tokens + [
            f"#{t[i : i + 3]}" for t in tokens if len(t) > 3 for i in range(len(t) - 2)
        ]
        for feat in features:
            h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dimensions
            sign = 1.0 if h[4] & 1 else -1.0
            weight = 1.0 if not feat.startswith("#") else 0.35
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class GatewayEmbeddings:
    """Embeddings through the LLM gateway; batches requests (``batch_size`` texts)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        dimensions: int = DIMENSIONS,
        batch_size: int = 64,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._batch = batch_size
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            batch = texts[start : start + self._batch]
            with tracer.start_as_current_span(
                "embeddings",
                attributes={
                    "gen_ai.operation.name": "embeddings",
                    "gen_ai.request.model": self.model,
                    "bomagent.batch_size": len(batch),
                },
            ):
                resp = await self._client.post(
                    "/v1/embeddings",
                    json={"model": self.model, "input": batch, "dimensions": self.dimensions},
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors = [d["embedding"] for d in data]
            if any(len(v) != self.dimensions for v in vectors):
                raise ValueError(f"gateway returned vectors not of size {self.dimensions}")
            out.extend(vectors)
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
