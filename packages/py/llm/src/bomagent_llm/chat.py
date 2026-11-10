"""Chat completions with structured output, through the LLM gateway (ADR-0006).

* ``GatewayChat`` - OpenAI-compatible ``/v1/chat/completions`` of LiteLLM with
  ``response_format = json_schema`` (structured output: no re-parsing loops, R7).
* ``FakeChat`` - deterministic provider for CI and local runs: replays recorded
  responses (cassettes, keyed by a hash of model + messages) and otherwise asks a
  ``responder`` function keyed by the prompt id. No network, no keys (CLAUDE.md rule 7).

Every call emits an OTel span with GenAI semantic-convention attributes and returns
``Usage`` (tokens, cost from the catalogue) for the thesis cost metrics.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from bomagent_bom.model import Usage
from bomagent_llm.catalog import Catalog, ModelSpec

tracer = trace.get_tracer(__name__)
T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """Gateway failure or a response that does not match the requested schema."""


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatRequest:
    prompt_id: str
    prompt_version: str
    model: ModelSpec
    messages: list[Message]
    schema_name: str
    json_schema: dict[str, Any]
    temperature: float = 0.0
    max_tokens: int = 4096
    metadata: dict[str, str] = field(default_factory=dict)

    def cache_key(self) -> str:
        body = json.dumps(
            {
                "model": self.model.gateway_model,
                "messages": [[m.role, m.content] for m in self.messages],
                "schema": self.schema_name,
            },
            sort_keys=True,
        )
        return hashlib.sha256(body.encode()).hexdigest()


@dataclass
class ChatResult:
    data: dict[str, Any]
    usage: Usage
    model_id: str
    raw: str = ""


class ChatClient(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResult: ...


async def structured[T: BaseModel](
    client: ChatClient, request: ChatRequest, schema: type[T]
) -> tuple[T, Usage]:
    """Run ``request`` and validate the JSON against ``schema`` (one retry on mismatch)."""
    total = Usage()
    for attempt in range(2):
        result = await client.complete(request)
        total = total + result.usage
        try:
            return schema.model_validate(result.data), total
        except ValidationError as exc:
            if attempt == 1:
                raise LlmError(f"{request.prompt_id}: response does not match schema") from exc
    raise AssertionError("unreachable")  # pragma: no cover


def _span_attrs(request: ChatRequest) -> dict[str, Any]:
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.system": request.model.provider,
        "gen_ai.request.model": request.model.gateway_model,
        "gen_ai.request.temperature": request.temperature,
        "gen_ai.request.max_tokens": request.max_tokens,
        "bomagent.prompt.id": request.prompt_id,
        "bomagent.prompt.version": request.prompt_version,
        "bomagent.model.license_class": request.model.license_class.value,
    }


def _usage(
    spec: ModelSpec, prompt_tokens: int, completion_tokens: int, seconds: float, cached: int = 0
) -> Usage:
    return Usage(
        llm_calls=1,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cached_input_tokens=cached,
        cost_eur=spec.cost(prompt_tokens, completion_tokens),
        wall_time_s=seconds,
    )


class GatewayChat:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def complete(self, request: ChatRequest) -> ChatResult:
        body = {
            "model": request.model.gateway_model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.json_schema,
                    "strict": False,
                },
            },
            # tenant/run tags for gateway budgets and Langfuse (no content in metadata)
            "metadata": request.metadata,
        }
        start = time.perf_counter()
        with tracer.start_as_current_span(
            f"chat {request.prompt_id}", attributes=_span_attrs(request)
        ) as span:
            resp = await self._client.post("/v1/chat/completions", json=body, headers=self._headers)
            if resp.status_code >= 400:
                raise LlmError(f"gateway returned {resp.status_code}")
            payload = resp.json()
            content = payload["choices"][0]["message"]["content"] or "{}"
            usage = payload.get("usage", {})
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.response.model", payload.get("model", ""))
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError(f"{request.prompt_id}: non-JSON response") from exc
        return ChatResult(
            data=data,
            usage=_usage(
                request.model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                time.perf_counter() - start,
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            ),
            model_id=request.model.id,
            raw=content,
        )


Responder = Callable[[ChatRequest], dict[str, Any]]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeChat:
    """Deterministic fake: cassette replay first, then the scripted ``responder``."""

    def __init__(self, responder: Responder, cassette_dir: str | Path | None = None) -> None:
        self._responder = responder
        self._cassettes: dict[str, dict[str, Any]] = {}
        self.calls: list[ChatRequest] = []
        if cassette_dir is not None and Path(cassette_dir).is_dir():
            for path in sorted(Path(cassette_dir).glob("*.json")):
                entry = json.loads(path.read_text(encoding="utf-8"))
                self._cassettes[entry["key"]] = entry["response"]

    async def complete(self, request: ChatRequest) -> ChatResult:
        self.calls.append(request)
        with tracer.start_as_current_span(
            f"chat {request.prompt_id}", attributes=_span_attrs(request)
        ):
            data = self._cassettes.get(request.cache_key()) or self._responder(request)
        prompt_text = "".join(m.content for m in request.messages)
        out = json.dumps(data)
        return ChatResult(
            data=data,
            usage=_usage(request.model, _estimate_tokens(prompt_text), _estimate_tokens(out), 0.0),
            model_id=request.model.id,
            raw=out,
        )


def record_cassette(directory: str | Path, request: ChatRequest, response: dict[str, Any]) -> Path:
    """Store a response for deterministic replay (used when recording with real models)."""
    path = Path(directory) / f"{request.prompt_id}-{request.cache_key()[:16]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"key": request.cache_key(), "prompt_id": request.prompt_id, "response": response},
            indent=2,
            sort_keys=True,
        )
    )
    return path


def resolve_model(catalog: Catalog, model_id: str) -> ModelSpec:
    return catalog.get(model_id)
