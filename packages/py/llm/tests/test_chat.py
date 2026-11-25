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


async def test_reasoning_models_get_room_for_their_thinking_tokens():
    """Mistral Large 4 thinks before it answers and the thinking counts against
    ``max_tokens``: a 1024-token MPN answer was cut off mid-JSON ("non-JSON response")."""
    from bomagent_llm.chat import call_timeout_s

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
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
    thinking = load_catalog().get("fake-closed").model_copy(update={"reasoning_tokens": 4096})
    await chat.complete(dataclasses.replace(_request(), model=thinking, max_tokens=1024))
    # max_completion_tokens: GPT-5 family on Azure rejects max_tokens; Mistral accepts both
    assert seen["max_completion_tokens"] == 1024 + 4096
    assert "max_tokens" not in seen
    assert seen["timeout"] == call_timeout_s(1024 + 4096)


def test_the_mistral_large_entry_is_pinned_and_reserves_reasoning_tokens():
    spec = load_catalog().get("mistral-large-eu")
    assert not spec.gateway_model.endswith("-latest")  # experiments need a fixed model
    assert spec.reasoning_tokens >= 4096


def _mistral_request(content: str = "hello " * 400) -> ChatRequest:
    return dataclasses.replace(_request(content), model=load_catalog().get("mistral-large-eu"))


def _gateway(handler) -> GatewayChat:
    return GatewayChat(
        "http://gw",
        "k",
        backoff_s=0.0,
        max_retries=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gw"),
    )


@pytest.mark.parametrize("failure", ["read_timeout", "status_408"])
async def test_a_timed_out_call_is_charged_an_estimate_and_flagged(failure):
    """I3: the provider bills a generation the gateway cut off, so a timeout is one call
    with (at least) the prompt tokens priced - flagged as an estimate, never silently 0."""

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "read_timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(408, json={"error": "timeout"})

    request = _mistral_request()
    with pytest.raises(LlmError) as info:
        await _gateway(handler).complete(request)
    exc = info.value
    assert exc.billing == "estimated"
    prompt_chars = sum(len(m.content) for m in request.messages)
    assert exc.usage.llm_calls == 1
    assert exc.usage.input_tokens == prompt_chars // 4
    assert exc.usage.cost_eur == request.model.cost(prompt_chars // 4, 0) > 0
    # the flag survives the structured-output wrapper
    with pytest.raises(LlmError) as wrapped:
        await structured(_gateway(handler), request, Answer)
    assert wrapped.value.billing == "estimated"
    assert wrapped.value.usage.llm_calls == 1


@pytest.mark.parametrize("status", [400, 401, 422, 500])
async def test_a_rejected_call_is_an_explicit_unbilled_zero(status):
    request = _mistral_request()
    with pytest.raises(LlmError) as info:
        await _gateway(lambda r: httpx.Response(status, json={"error": "x"})).complete(request)
    assert info.value.billing == "unbilled"
    assert info.value.usage.llm_calls == 1
    assert (info.value.usage.input_tokens, info.value.usage.cost_eur) == (0, 0.0)


async def test_a_failed_call_with_usage_is_metered():
    def bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not json"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    with pytest.raises(LlmError) as info:
        await _gateway(bad_json).complete(_mistral_request())
    assert info.value.billing == "metered"
    assert (info.value.usage.input_tokens, info.value.usage.output_tokens) == (10, 3)


@pytest.mark.parametrize(
    ("content", "finish_reason"), [("", "stop"), (None, "stop"), ('{"mpn": "X', "length")]
)
async def test_an_empty_or_truncated_answer_is_a_paid_failure(content, finish_reason):
    """M6: an empty or length-cut reply is not an all-default answer ("no MPN")."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 9},
            },
        )

    with pytest.raises(LlmError, match=r"empty|truncated") as info:
        await _gateway(handler).complete(_mistral_request())
    assert info.value.usage.output_tokens == 9
    assert info.value.billing == "metered"


async def test_replay_only_fake_raises_on_a_cassette_miss(tmp_path):
    """I4: replaying a real model's cassettes must never fall back to a scripted answer."""
    from bomagent_llm.chat import CassetteMissError

    recorded = _mistral_request("recorded")
    record_cassette(tmp_path / "mistral-large-eu", recorded, {"mpn": "REAL"})
    replay = FakeChat(None, cassette_dir=tmp_path)
    assert (await replay.complete(recorded)).data == {"mpn": "REAL"}
    with pytest.raises(CassetteMissError, match="mpn_select"):
        await replay.complete(_mistral_request("never recorded"))
    assert not issubclass(CassetteMissError, LlmError)  # a broken replay is not a model failure
