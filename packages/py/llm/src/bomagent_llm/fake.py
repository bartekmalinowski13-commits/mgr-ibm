"""Deterministic fake LLM provider for tests, CI and offline development (TESTING.md).

Resolution order for a request:

1. **Cassette** - a recorded response keyed by a hash of the request (model, messages,
   schema, tools; metadata except ``prompt_id``/``prompt_version`` is ignored so tenant and
   run ids do not break replay).
2. **Simulator** - a deterministic function registered for the prompt (``metadata
   ["prompt_id"]``). Simulators live next to the prompts (``bomagent_agents.simulators``)
   and emulate a competent model so pipelines can run end to end without a network.
3. Otherwise :class:`FakeMissError`.

Results produced by simulators are *plumbing* results, never research data.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable
from pathlib import Path

from bomagent_llm.chat import ChatRequest, ChatResponse

Simulator = Callable[[ChatRequest], ChatResponse]


class FakeMissError(LookupError):
    """No cassette and no simulator for this request."""


def request_key(request: ChatRequest) -> str:
    keep = {k: v for k, v in request.metadata.items() if k in {"prompt_id", "prompt_version"}}
    canonical = request.model_copy(update={"metadata": keep}).model_dump(mode="json")
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


def approx_tokens(text: str) -> int:
    """Deterministic token estimate (~4 characters per token)."""
    return max(1, len(text) // 4)


def request_tokens(request: ChatRequest) -> int:
    total = sum(approx_tokens(m.content or "") for m in request.messages)
    total += sum(
        approx_tokens(json.dumps(c.arguments)) for m in request.messages for c in m.tool_calls
    )
    if request.response_schema:
        total += approx_tokens(json.dumps(request.response_schema))
    return total


class CassetteStore:
    """Directory of ``<sha256>.json`` files holding :class:`ChatResponse` bodies."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def get(self, request: ChatRequest) -> ChatResponse | None:
        path = self.directory / f"{request_key(request)}.json"
        if not path.is_file():
            return None
        return ChatResponse.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, request: ChatRequest, response: ChatResponse) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{request_key(request)}.json"
        path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        return path


class FakeChat:
    """``ChatClient`` that never touches the network."""

    def __init__(
        self,
        simulator: Simulator | None = None,
        cassettes: CassetteStore | None = None,
        *,
        record: bool = False,
    ) -> None:
        self.simulator = simulator
        self.cassettes = cassettes
        self.record = record
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.cassettes is not None:
            hit = self.cassettes.get(request)
            if hit is not None:
                return hit
        if self.simulator is None:
            raise FakeMissError(
                f"no cassette or simulator for prompt {request.metadata.get('prompt_id')!r}"
            )
        response = self.simulator(request)
        if response.input_tokens == 0:
            response = response.model_copy(update={"input_tokens": request_tokens(request)})
        if response.output_tokens == 0:
            out_text = response.content + "".join(
                json.dumps(c.arguments) for c in response.tool_calls
            )
            response = response.model_copy(update={"output_tokens": approx_tokens(out_text)})
        if not response.model:
            response = response.model_copy(update={"model": request.model})
        if self.record and self.cassettes is not None:
            self.cassettes.put(request, response)
        return response


def load_simulator(spec: str) -> Simulator:
    """``"package.module:attr"`` -> simulator callable."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"simulator spec must be 'module:attr', got {spec!r}")
    fn = getattr(importlib.import_module(module_name), attr)
    if not callable(fn):
        raise TypeError(f"{spec} is not callable")
    return fn  # type: ignore[no-any-return]
