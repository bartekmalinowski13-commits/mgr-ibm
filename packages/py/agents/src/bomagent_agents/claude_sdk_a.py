"""Variant A on a ready-made agent loop: Claude Agent SDK adapter (ADR-0007).

The SDK runs its own tool loop; we expose three in-process MCP tools bound to the run:

* ``get_components`` - the parsed design (untrusted data),
* ``search_kb`` - tenant-scoped knowledge retrieval with MPN candidates,
* ``submit_bom`` - the only way to return the result (schema-validated here).

Built-in tools (file system, shell, web) are **not** allowed: the agent cannot execute
code or reach the network (SECURITY.md, prompt injection). EU processing: the SDK is
pointed at the LLM gateway (``ANTHROPIC_BASE_URL``) or at Amazon Bedrock in an EU region
(``CLAUDE_CODE_USE_BEDROCK=1``, ``AWS_REGION=eu-central-1``) - configured by the
deployment, never the public endpoint. The SDK is an optional dependency
(``claude-agent-sdk``); tests inject a fake ``query`` function.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from bomagent_agents.contracts import RunInput, RunOutput, TraceStep
from bomagent_agents.prompts import data_block, load_prompt
from bomagent_agents.runtime_base import AgentContext, agent_provenance
from bomagent_agents.schemas import GroupedLines
from bomagent_agents.variant_a import lines_to_items
from bomagent_bom.model import BomVersion, Finding, Severity, Usage

TOOL_NAMES = ["mcp__bom__get_components", "mcp__bom__search_kb", "mcp__bom__submit_bom"]
# allowed_tools only pre-approves; built-in tools must be denied explicitly
BUILTIN_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "Task",
    "TodoWrite",
]
SUBMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "refdes": {"type": "array", "items": {"type": "string"}},
                    "quantity": {"type": "integer"},
                    "value": {"type": "string"},
                    "footprint": {"type": "string"},
                    "mpn": {"type": "string"},
                    "manufacturer": {"type": "string"},
                    "dnp": {"type": "boolean"},
                },
                "required": ["refdes"],
            },
        }
    },
    "required": ["lines"],
}


class SdkUnavailableError(RuntimeError):
    pass


def _text(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


class _LocalTool:
    def __init__(self, name: str, handler: Callable[..., Any]) -> None:
        self.name, self.handler = name, handler


def _local_tool(name: str, _description: str, _schema: dict[str, Any]) -> Any:
    def wrap(fn: Callable[..., Any]) -> _LocalTool:
        return _LocalTool(name, fn)

    return wrap


class ClaudeAgentSdkVariantA:
    name = "claude_agent_sdk_a"

    def __init__(
        self,
        ctx_factory: Callable[[RunInput], AgentContext],
        *,
        query_fn: Callable[..., AsyncIterator[Any]] | None = None,
        max_turns: int = 40,
    ) -> None:
        self._ctx_factory = ctx_factory
        self._query_fn = query_fn
        self._max_turns = max_turns

    def _tools(self, ctx: AgentContext, run: RunInput, sink: dict[str, Any]) -> list[Any]:
        try:
            from claude_agent_sdk import tool
        except ImportError:  # SDK not installed: same shape (name + handler) for tests
            tool = _local_tool

        @tool("get_components", "Components of the design (untrusted data)", {})  # type: ignore[untyped-decorator]
        async def get_components(_: dict[str, Any]) -> dict[str, Any]:
            comps = [c.model_dump(mode="json") for c in run.design.components]
            return {
                "content": [{"type": "text", "text": data_block("components", json.dumps(comps))}]
            }

        @tool("search_kb", "Search component documentation", {"query": str})  # type: ignore[untyped-decorator]
        async def search_kb(args: dict[str, Any]) -> dict[str, Any]:
            (ev,) = await ctx.retriever.evidence([str(args["query"])], ctx.config.kb_k)
            ctx.evidence_mpns |= {c.mpn.strip().upper() for c in ev.candidates}
            payload = {
                "candidates": [c.__dict__ for c in ev.candidates],
                "excerpts": [h.content[:800] for h in ev.hits if not h.injection_suspect],
            }
            return {
                "content": [{"type": "text", "text": data_block("knowledge", json.dumps(payload))}]
            }

        @tool("submit_bom", "Submit the final BOM lines", SUBMIT_SCHEMA)  # type: ignore[untyped-decorator]
        async def submit_bom(args: dict[str, Any]) -> dict[str, Any]:
            sink["bom"] = GroupedLines.model_validate({"lines": args["lines"]})
            return _text({"accepted": len(sink["bom"].lines)})

        return [get_components, search_kb, submit_bom]

    async def run(self, run: RunInput) -> RunOutput:
        ctx = self._ctx_factory(run)
        prompt = load_prompt("claude_agent_sdk")
        sink: dict[str, Any] = {}
        start = time.perf_counter()
        # the run budget (R7) applies to the SDK loop too: turns <= LLM calls, wall time
        max_turns = min(self._max_turns, run.config.max_llm_calls)
        query_fn = self._query_fn
        options: Any = None
        if query_fn is None:  # pragma: no cover - real SDK path, exercised manually
            try:
                from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
            except ImportError as exc:
                raise SdkUnavailableError("install claude-agent-sdk") from exc
            server = create_sdk_mcp_server(
                name="bom", version="1.0.0", tools=self._tools(ctx, run, sink)
            )
            options = ClaudeAgentOptions(
                system_prompt=prompt.text,
                mcp_servers={"bom": server},
                allowed_tools=TOOL_NAMES,
                disallowed_tools=BUILTIN_TOOLS,
                setting_sources=[],
                max_turns=max_turns,
                model=ctx.model.gateway_model.split("/")[-1],
            )
            query_fn = query
        else:
            options = {"tools": self._tools(ctx, run, sink), "sink": sink, "max_turns": max_turns}
        usage = Usage()
        status: Literal["completed", "failed", "budget_exceeded"] = "completed"
        budget_errors: list[str] = []

        async def consume() -> None:
            nonlocal usage
            async for message in query_fn(
                prompt="Create the BOM for this design.", options=options
            ):
                kind = type(message).__name__
                if kind == "AssistantMessage":
                    # running total per turn: a run stopped by the time budget never sees
                    # the final ResultMessage, and its spend must still be metered
                    u = getattr(message, "usage", None) or {}
                    usage = usage + Usage(
                        llm_calls=1,
                        input_tokens=int(u.get("input_tokens", 0)),
                        output_tokens=int(u.get("output_tokens", 0)),
                        cached_input_tokens=int(u.get("cache_read_input_tokens", 0)),
                    )
                if kind == "ResultMessage":  # authoritative totals of the whole loop
                    u = getattr(message, "usage", None) or {}
                    usage = Usage(
                        llm_calls=int(getattr(message, "num_turns", 0) or 0),
                        input_tokens=int(u.get("input_tokens", 0)),
                        output_tokens=int(u.get("output_tokens", 0)),
                        cached_input_tokens=int(u.get("cache_read_input_tokens", 0)),
                    )
                    if getattr(message, "subtype", "") == "error_max_turns":
                        budget_errors.append(f"limit of {max_turns} agent turns reached")

        try:
            async with asyncio.timeout(run.config.timeout_s):
                await consume()
        except TimeoutError:
            budget_errors.append(f"run longer than {run.config.timeout_s} s")
        if usage.input_tokens + usage.output_tokens > run.config.max_total_tokens:
            budget_errors.append(f"more than {run.config.max_total_tokens} tokens")
        wall = time.perf_counter() - start
        usage = usage.model_copy(
            update={
                "wall_time_s": wall,
                "cost_eur": ctx.model.cost(usage.input_tokens, usage.output_tokens),
            }
        )
        findings: list[Finding] = [
            Finding(rule_id="run.budget", severity=Severity.ERROR, message=f"claude_agent_sdk: {e}")
            for e in budget_errors
        ]
        if budget_errors:
            status = "budget_exceeded"
        elif "bom" not in sink:
            status = "failed"
            findings.append(
                Finding(
                    rule_id="run.no_result",
                    severity=Severity.ERROR,
                    message="the agent finished without calling submit_bom",
                )
            )
        prov = agent_provenance("claude_agent_sdk", prompt, ctx.model, "Claude Agent SDK loop")
        items = (
            ctx.guard_mpns(lines_to_items(ctx, sink["bom"].lines, prov, "submit_bom"), "submit_bom")
            if "bom" in sink
            else []
        )
        findings += ctx.issues
        bom = BomVersion(
            id=run.run_id,
            design_name=run.design.design_name,
            variant="A",
            items=items,
            findings=findings,
            usage=usage,
            kb_snapshot_id=run.config.kb_snapshot_id,
        )
        return RunOutput(
            run_id=run.run_id,
            runtime=self.name,
            bom=bom,
            trace=[TraceStep(node="claude_agent_sdk", duration_s=wall, llm_calls=usage.llm_calls)],
            usage=usage,
            status=status,
        )
