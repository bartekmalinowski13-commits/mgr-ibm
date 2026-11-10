from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bomagent_llm.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    GatewayChat,
    GatewayError,
    ToolCall,
    ToolSpec,
    from_openai_payload,
    to_openai_payload,
)
from bomagent_llm.fake import (
    CassetteStore,
    FakeChat,
    FakeMissError,
    load_simulator,
    request_key,
)
from bomagent_llm.fake_server import create_app, request_from_openai, response_to_openai


def _req(**kw) -> ChatRequest:
    base = {
        "model": "fake-closed",
        "messages": [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hello"),
        ],
        "metadata": {"prompt_id": "p", "prompt_version": "1", "tenant_id": "t1", "run_id": "r1"},
    }
    return ChatRequest(**(base | kw))


def test_openai_payload_has_schema_tools_metadata_and_user():
    req = _req(
        response_schema={"type": "object"},
        schema_name="Out",
        tools=[ToolSpec(name="t", description="d", parameters={"type": "object"})],
        messages=[
            ChatMessage(role="user", content="x"),
            ChatMessage(
                role="assistant", tool_calls=[ToolCall(id="c1", name="t", arguments={"a": 1})]
            ),
            ChatMessage(role="tool", tool_call_id="c1", name="t", content="{}"),
        ],
    )
    p = to_openai_payload(req)
    assert p["response_format"]["json_schema"]["name"] == "Out"
    assert p["tools"][0]["function"]["name"] == "t"
    assert p["user"] == "t1"
    assert p["metadata"]["prompt_id"] == "p"
    assert json.loads(p["messages"][1]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
    assert p["messages"][2]["tool_call_id"] == "c1"


def test_from_openai_payload_parses_usage_and_tool_calls():
    body = {
        "model": "m",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": '{"x": 2}'}}],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    r = from_openai_payload(body)
    assert r.tool_calls[0].arguments == {"x": 2}
    assert (r.input_tokens, r.output_tokens, r.cached_input_tokens) == (10, 3, 4)
    with pytest.raises(GatewayError):
        from_openai_payload({"choices": []})
    bad = {
        "choices": [
            {"message": {"tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{"}}]}}
        ]
    }
    with pytest.raises(GatewayError, match="not JSON"):
        from_openai_payload(bad)


async def test_gateway_chat_roundtrip_and_errors():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        if seen["body"]["model"] == "boom":
            return httpx.Response(429, text="budget exceeded")
        return httpx.Response(
            200,
            json={
                "model": "fake-closed",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    client = httpx.AsyncClient(base_url="http://gw", transport=httpx.MockTransport(handler))
    chat = GatewayChat("http://gw", "sk-test", client=client)
    out = await chat.complete(_req())
    assert out.content == '{"ok": true}'
    assert out.input_tokens == 5
    assert seen["auth"] == "Bearer sk-test"
    with pytest.raises(GatewayError, match="429"):
        await chat.complete(_req(model="boom"))
    await chat.aclose()


async def test_fake_chat_cassette_then_simulator_then_miss(tmp_path):
    store = CassetteStore(tmp_path)
    calls = []

    def sim(req: ChatRequest) -> ChatResponse:
        calls.append(req)
        return ChatResponse(content="from-sim")

    recorder = FakeChat(sim, store, record=True)
    first = await recorder.complete(_req())
    assert first.content == "from-sim"
    assert first.input_tokens > 0
    assert first.output_tokens > 0
    assert first.model == "fake-closed"
    # tenant/run metadata does not change the key -> replayed without the simulator
    replay = FakeChat(None, store)
    again = await replay.complete(
        _req(metadata={"prompt_id": "p", "prompt_version": "1", "tenant_id": "other"})
    )
    assert again.content == "from-sim"
    assert len(calls) == 1
    with pytest.raises(FakeMissError):
        await FakeChat().complete(_req())
    assert request_key(_req()) != request_key(_req(model="x"))


def test_load_simulator():
    fn = load_simulator("json:dumps")
    assert fn({"a": 1}) == '{"a": 1}'  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="module:attr"):
        load_simulator("nocolon")
    with pytest.raises(TypeError):
        load_simulator("json:__name__")


def test_fake_server_chat_embeddings_and_miss():
    def sim(req: ChatRequest) -> ChatResponse:
        if req.metadata.get("prompt_id") == "tool":
            return ChatResponse(
                tool_calls=[ToolCall(id="c", name="f", arguments={"q": 1})],
                finish_reason="tool_calls",
            )
        return ChatResponse(content=json.dumps({"echo": req.messages[-1].content}))

    client = TestClient(create_app(FakeChat(sim)))
    assert client.get("/healthz").json() == {"status": "ok"}
    body = {
        "model": "fake-closed",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "X", "schema": {}}},
        "metadata": {"prompt_id": "p"},
    }
    r = client.post("/v1/chat/completions", json=body).json()
    assert json.loads(r["choices"][0]["message"]["content"]) == {"echo": "hi"}
    r = client.post("/v1/chat/completions", json=body | {"metadata": {"prompt_id": "tool"}}).json()
    assert r["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "f"
    e = client.post("/v1/embeddings", json={"input": "abc", "dimensions": 8}).json()
    assert len(e["data"][0]["embedding"]) == 8
    miss = TestClient(create_app(FakeChat()))
    assert miss.post("/v1/chat/completions", json=body).status_code == 404


def test_server_translation_roundtrip():
    req = request_from_openai(
        {
            "model": "m",
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c", "name": "f", "content": "{}"},
            ],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {}}}],
        }
    )
    assert req.tools[0].name == "f"
    assert req.messages[1].tool_call_id == "c"
    out = response_to_openai(ChatResponse(content="x", model="m", input_tokens=1, output_tokens=2))
    assert out["usage"]["total_tokens"] == 3
