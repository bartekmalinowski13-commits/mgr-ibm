from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from bomagent_llm.catalog import load_catalog
from bomagent_llm.chat import (
    ChatRequest,
    FakeChat,
    GatewayChat,
    LlmError,
    Message,
    record_cassette,
    resolve_model,
    structured,
)


class Answer(BaseModel):
    mpn: str


def _request(content: str = "hello") -> ChatRequest:
    return ChatRequest(
        prompt_id="mpn_select",
        prompt_version="1+abc",
        model=load_catalog().get("fake-closed"),
        messages=[Message("system", "s"), Message("user", content)],
        schema_name="Answer",
        json_schema=Answer.model_json_schema(),
        metadata={"run_id": "r"},
    )


async def test_gateway_chat_sends_structured_output_and_parses_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={
                "model": "fake-closed",
                "choices": [{"message": {"content": '{"mpn": "X1"}'}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 40},
                },
            },
        )

    chat = GatewayChat(
        "http://gw",
        "k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw"),
    )
    answer, usage = await structured(chat, _request(), Answer)
    assert answer.mpn == "X1"
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["metadata"] == {"run_id": "r"}
    assert (
        usage.llm_calls,
        usage.input_tokens,
        usage.output_tokens,
        usage.cached_input_tokens,
    ) == (1, 100, 5, 40)


@pytest.mark.parametrize(
    ("status", "content", "match"),
    [(500, "{}", "gateway returned 500"), (200, "not json", "non-JSON")],
)
async def test_gateway_errors(status, content, match):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
    )
    chat = GatewayChat(
        "http://gw", "k", client=httpx.AsyncClient(transport=transport, base_url="http://gw")
    )
    with pytest.raises(LlmError, match=match):
        await chat.complete(_request())


async def test_structured_retries_once_then_fails():
    answers = iter([{"wrong": 1}, {"mpn": "OK"}])
    chat = FakeChat(lambda r: next(answers))
    answer, usage = await structured(chat, _request(), Answer)
    assert answer.mpn == "OK"
    assert usage.llm_calls == 2
    with pytest.raises(LlmError, match="does not match schema"):
        await structured(FakeChat(lambda r: {"wrong": 1}), _request(), Answer)


async def test_cassettes_take_precedence_and_keys_are_stable(tmp_path):
    req = _request("abc")
    assert req.cache_key() == _request("abc").cache_key()
    assert req.cache_key() != _request("abd").cache_key()
    record_cassette(tmp_path, req, {"mpn": "RECORDED"})
    chat = FakeChat(lambda r: {"mpn": "SCRIPTED"}, cassette_dir=tmp_path)
    assert (await chat.complete(req)).data == {"mpn": "RECORDED"}
    assert (await chat.complete(_request("other"))).data == {"mpn": "SCRIPTED"}
    assert resolve_model(load_catalog(), "fake-closed").id == "fake-closed"


async def test_gateway_retries_rate_limits_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"mpn": "R"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    chat = GatewayChat(
        "http://gw",
        "k",
        backoff_s=0.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw"),
    )
    assert (await chat.complete(_request())).data == {"mpn": "R"}
    assert calls["n"] == 3


async def test_gateway_gives_up_and_wraps_transport_errors():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    chat = GatewayChat(
        "http://gw",
        "k",
        backoff_s=0.0,
        max_retries=1,
        client=httpx.AsyncClient(transport=httpx.MockTransport(down), base_url="http://gw"),
    )
    with pytest.raises(LlmError, match="unreachable"):
        await chat.complete(_request())
    malformed = GatewayChat(
        "http://gw",
        "k",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"x": 1})),
            base_url="http://gw",
        ),
    )
    with pytest.raises(LlmError, match="malformed"):
        await malformed.complete(_request())


async def test_cassette_replays_recorded_usage(tmp_path):
    from bomagent_bom.model import Usage

    req = _request("u")
    record_cassette(
        tmp_path,
        req,
        {"mpn": "X"},
        Usage(llm_calls=1, input_tokens=1234, output_tokens=56, cost_eur=0.01),
    )
    result = await FakeChat(lambda r: {}, cassette_dir=tmp_path).complete(req)
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1234, 56)
