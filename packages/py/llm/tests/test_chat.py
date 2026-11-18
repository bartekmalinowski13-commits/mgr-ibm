from __future__ import annotations

import dataclasses
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


async def test_recording_chat_writes_per_model_cassettes_and_replays(tmp_path):
    from bomagent_llm.chat import RecordingChat

    calls = []

    def responder(r):
        calls.append(r)
        return {"mpn": "REAL"}

    req = _request("rec")
    recorder = RecordingChat(FakeChat(responder), tmp_path)
    live = await recorder.complete(req)
    assert len(recorder.recorded) == 1
    assert recorder.recorded[0].parent == tmp_path / req.model.id
    # replay without the inner provider: identical data and the recorded usage
    replay = await FakeChat(lambda r: {"mpn": "SCRIPTED"}, cassette_dir=tmp_path).complete(req)
    assert replay.data == {"mpn": "REAL"}
    assert replay.usage.input_tokens == live.usage.input_tokens
    assert len(calls) == 1
    # nothing secret-shaped is stored
    assert "authorization" not in recorder.recorded[0].read_text().lower()


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


def test_call_timeout_grows_with_max_tokens_and_is_capped():
    from bomagent_llm.chat import CALL_TIMEOUT_MAX_S, call_timeout_s

    assert call_timeout_s(1024) < call_timeout_s(8_000) < call_timeout_s(16_000)
    assert call_timeout_s(8_000) >= 300  # validate: ~8k tokens at a slow provider rate
    assert call_timeout_s(1_000_000) == CALL_TIMEOUT_MAX_S


async def test_gateway_chat_passes_a_per_call_timeout_sized_to_max_tokens():
    from bomagent_llm.chat import call_timeout_s

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["read"] = request.extensions["timeout"]["read"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"mpn": "X"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    chat = GatewayChat(
        "http://gw",
        "k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw"),
    )
    await chat.complete(dataclasses.replace(_request(), max_tokens=8_000))
    # the gateway gets the same budget (LiteLLM per-request ``timeout``); the client waits a
    # little longer so the gateway's answer (or its timeout error) arrives first
    assert seen["body"]["timeout"] == call_timeout_s(8_000)
    assert seen["read"] > call_timeout_s(8_000)


@pytest.mark.parametrize("failure", ["read_timeout", "status_408"])
async def test_a_timed_out_generation_is_not_repeated(failure):
    """Retrying a call that ran out of time repeats the same long (paid) generation."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if failure == "read_timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(408, json={"error": "timeout"})

    chat = GatewayChat(
        "http://gw",
        "k",
        backoff_s=0.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw"),
    )
    with pytest.raises(LlmError, match=r"timed out|408"):
        await chat.complete(_request())
    assert calls["n"] == 1
