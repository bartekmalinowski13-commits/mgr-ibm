"""OpenAI-compatible fake model server for the local stack and CI (behind LiteLLM).

``/v1/chat/completions`` answers with cassettes or the heuristic responder (prompt id is
taken from request metadata), ``/v1/embeddings`` with deterministic hashing vectors.
Never deployed to the cloud. Run: ``python -m bomagent_agents.fake_server``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI

from bomagent_agents.fake_responder import heuristic_responder
from bomagent_llm.catalog import load_catalog
from bomagent_llm.chat import ChatRequest, FakeChat, Message
from bomagent_llm.embeddings import HashingEmbeddings


def create_app(cassette_dir: str | None = None) -> FastAPI:
    app = FastAPI(title="fake-llm", docs_url=None, redoc_url=None)
    chat = FakeChat(
        heuristic_responder, cassette_dir or os.environ.get("BOMAGENT_FAKE_LLM_CASSETTES")
    )
    emb = HashingEmbeddings()
    catalog = load_catalog()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "fake-llm"}

    @app.post("/v1/chat/completions")
    async def completions(body: dict[str, Any]) -> dict[str, Any]:
        meta = body.get("metadata") or {}
        model = next(
            (
                m
                for m in catalog.models
                if m.gateway_model == body["model"] or m.id == body["model"]
            ),
            catalog.get("fake-closed"),
        )
        request = ChatRequest(
            prompt_id=str(meta.get("prompt_id", "")),
            prompt_version="?",
            model=model,
            messages=[Message(m["role"], m["content"]) for m in body["messages"]],
            schema_name="",
            json_schema={},
        )
        result = await chat.complete(request)
        return {
            "id": "fake",
            "object": "chat.completion",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(result.data)},
                }
            ],
            "usage": {
                "prompt_tokens": result.usage.input_tokens,
                "completion_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.input_tokens + result.usage.output_tokens,
            },
        }

    @app.post("/v1/embeddings")
    async def embeddings(body: dict[str, Any]) -> dict[str, Any]:
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        vectors = await emb.embed([str(t) for t in texts])
        return {
            "object": "list",
            "model": body.get("model", "fake-embedding"),
            "data": [
                {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
            ],
            "usage": {
                "prompt_tokens": sum(len(str(t)) // 4 for t in texts),
                "total_tokens": sum(len(str(t)) // 4 for t in texts),
            },
        }

    return app


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(
        create_app(),
        host=os.environ.get("BOMAGENT_HOST", "0.0.0.0"),  # noqa: S104
        port=int(os.environ.get("BOMAGENT_PORT", "4010")),
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
