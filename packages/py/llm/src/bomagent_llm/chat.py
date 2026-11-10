"""Chat completions through the LLM gateway (ADR-0006).

One provider-neutral request/response model. ``GatewayChat`` speaks the OpenAI-compatible
``/v1/chat/completions`` API of LiteLLM (structured output via ``response_format`` JSON
Schema, tools via function calling). The platform never calls a provider SDK directly:
the gateway enforces the EU allow-list, budgets per tenant and logging.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

import httpx
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

tracer = trace.get_tracer(__name__)

Role = Literal["system", "user", "assistant", "tool"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolCall(_Model):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(_Model):
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(_Model):
    name: str
    description: str
    parameters: dict[str, Any]


class ChatRequest(_Model):
    """A single completion request. ``metadata`` carries prompt id/version, tenant, run and
    agent name - used for tracing, budgets in the gateway and the fake provider."""

    model: str
    messages: list[ChatMessage]
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int = 4096
    metadata: dict[str, str] = Field(default_factory=dict)


class ChatResponse(_Model):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str = ""
    finish_reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class ChatClient(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse: ...


class GatewayError(RuntimeError):
    """The gateway answered with an error or an unparsable body."""


def to_openai_payload(request: ChatRequest) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for m in request.messages:
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in m.tool_calls
            ]
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.name:
            msg["name"] = m.name
        messages.append(msg)
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.schema_name or "result",
                "schema": request.response_schema,
                "strict": False,
            },
        }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    if request.metadata:
        payload["metadata"] = dict(request.metadata)
        if "tenant_id" in request.metadata:
            payload["user"] = request.metadata["tenant_id"]
    return payload


def from_openai_payload(body: dict[str, Any]) -> ChatResponse:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GatewayError(f"unexpected completion body: {str(body)[:200]}") from exc
    calls: list[ToolCall] = []
    for c in message.get("tool_calls") or []:
        raw = c.get("function", {}).get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError as exc:
            raise GatewayError(f"tool call arguments are not JSON: {raw[:200]}") from exc
        calls.append(ToolCall(id=str(c.get("id", "")), name=c["function"]["name"], arguments=args))
    usage = body.get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return ChatResponse(
        content=message.get("content") or "",
        tool_calls=calls,
        model=str(body.get("model", "")),
        finish_reason=str(choice.get("finish_reason") or "stop"),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        cached_input_tokens=int(details.get("cached_tokens") or 0),
    )


class GatewayChat:
    """Client of the LiteLLM gateway (OpenAI-compatible chat completions)."""

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

    async def complete(self, request: ChatRequest) -> ChatResponse:
        attrs: dict[str, str | float] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": request.model,
            "gen_ai.request.temperature": request.temperature,
            "bomagent.prompt_id": request.metadata.get("prompt_id", ""),
            "bomagent.agent": request.metadata.get("agent", ""),
        }
        with tracer.start_as_current_span("chat " + request.model, attributes=attrs) as span:
            resp = await self._client.post(
                "/v1/chat/completions", json=to_openai_payload(request), headers=self._headers
            )
            if resp.status_code >= 400:
                raise GatewayError(f"gateway HTTP {resp.status_code}: {resp.text[:300]}")
            out = from_openai_payload(resp.json())
            span.set_attribute("gen_ai.usage.input_tokens", out.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", out.output_tokens)
            span.set_attribute("gen_ai.response.finish_reasons", [out.finish_reason])
            return out

    async def aclose(self) -> None:
        await self._client.aclose()
