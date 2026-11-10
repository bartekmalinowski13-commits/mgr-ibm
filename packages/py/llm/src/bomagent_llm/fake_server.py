"""OpenAI-compatible fake LLM server used behind LiteLLM in the local stack and CI.

Run with ``python -m bomagent_llm.fake_server``. Environment:

* ``BOMAGENT_FAKE_LLM_CASSETTES`` - directory with recorded responses (optional)
* ``BOMAGENT_FAKE_LLM_SIMULATOR`` - ``module:attr`` of a simulator (optional;
  the compose stack uses ``bomagent_agents.simulators:simulate``)
* ``BOMAGENT_PORT`` - listen port (default 4010)

Endpoints: ``POST /v1/chat/completions``, ``POST /v1/embeddings``, ``GET /healthz``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from bomagent_llm.chat import ChatMessage, ChatRequest, ChatResponse, ToolCall, ToolSpec
from bomagent_llm.embeddings import HashingEmbeddings
from bomagent_llm.fake import CassetteStore, FakeChat, FakeMissError, load_simulator


def request_from_openai(body: dict[str, Any]) -> ChatRequest:
    messages: list[ChatMessage] = []
    for m in body.get("messages", []):
        calls = [
            ToolCall(
                id=str(c.get("id", "")),
                name=c["function"]["name"],
                arguments=json.loads(c["function"].get("arguments") or "{}"),
            )
            for c in m.get("tool_calls") or []
        ]
        content = m.get("content")
        if isinstance(content, list):  # content parts -> text
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        messages.append(
            ChatMessage(
                role=m["role"],
                content=content,
                tool_calls=calls,
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
            )
        )
    schema = None
    schema_name = None
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_schema":
        schema = fmt["json_schema"].get("schema")
        schema_name = fmt["json_schema"].get("name")
    tools = [
        ToolSpec(
            name=t["function"]["name"],
            description=t["function"].get("description", ""),
            parameters=t["function"].get("parameters", {}),
        )
        for t in body.get("tools") or []
    ]
    metadata = {str(k): str(v) for k, v in (body.get("metadata") or {}).items()}
    return ChatRequest(
        model=str(body.get("model", "fake")),
        messages=messages,
        response_schema=schema,
        schema_name=schema_name,
        tools=tools,
        temperature=float(body.get("temperature") or 0.0),
        max_tokens=int(body.get("max_tokens") or 4096),
        metadata=metadata,
    )


def response_to_openai(resp: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": resp.content or None}
    if resp.tool_calls:
        message["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in resp.tool_calls
        ]
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": resp.model,
        "choices": [{"index": 0, "message": message, "finish_reason": resp.finish_reason}],
        "usage": {
            "prompt_tokens": resp.input_tokens,
            "completion_tokens": resp.output_tokens,
            "total_tokens": resp.input_tokens + resp.output_tokens,
            "prompt_tokens_details": {"cached_tokens": resp.cached_input_tokens},
        },
    }


def create_app(chat: FakeChat | None = None) -> FastAPI:
    if chat is None:
        cassettes = os.environ.get("BOMAGENT_FAKE_LLM_CASSETTES")
        simulator = os.environ.get("BOMAGENT_FAKE_LLM_SIMULATOR")
        chat = FakeChat(
            simulator=load_simulator(simulator) if simulator else None,
            cassettes=CassetteStore(cassettes) if cassettes else None,
        )
    embedder = HashingEmbeddings()
    app = FastAPI(title="fake-llm", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(body: dict[str, Any]) -> JSONResponse:
        try:
            resp = await chat.complete(request_from_openai(body))
        except FakeMissError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(response_to_openai(resp))

    @app.post("/v1/embeddings")
    async def embeddings(body: dict[str, Any]) -> dict[str, Any]:
        texts = body.get("input") or []
        if isinstance(texts, str):
            texts = [texts]
        dims = int(body.get("dimensions") or embedder.dimensions)
        local = embedder if dims == embedder.dimensions else HashingEmbeddings(dims)
        vectors = await local.embed([str(t) for t in texts])
        return {
            "object": "list",
            "model": body.get("model", "fake-embedding"),
            "data": [
                {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    return app


def main() -> None:  # pragma: no cover - container entrypoint
    import uvicorn

    uvicorn.run(
        create_app(),
        host=os.environ.get("BOMAGENT_HOST", "0.0.0.0"),  # noqa: S104 - container port
        port=int(os.environ.get("BOMAGENT_PORT", "4010")),
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
