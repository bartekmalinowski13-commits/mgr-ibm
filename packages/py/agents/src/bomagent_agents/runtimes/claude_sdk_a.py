"""Variant A on a ready-made agent loop (Claude Agent SDK) - experimental adapter (ADR-0007).

One autonomous agent gets the whole task and three tools (CAD read, knowledge-base
search) and must return the final BOM as JSON. This lets the thesis compare "our own
LangGraph multi-agent graph" with "a vendor agent loop" behind the same contract.

Residency (ADR-0006): the SDK calls the model directly, not through the LLM gateway. The
adapter therefore refuses to start unless the SDK is configured for Amazon Bedrock in an
EU region (``CLAUDE_CODE_USE_BEDROCK=1`` and ``AWS_REGION=eu-*``). The SDK API is used
only inside :class:`ClaudeSdkLoop`; everything else is tested with a scripted loop.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from bomagent_agents.context import AgentLLM, RunConfig, RunState
from bomagent_agents.prompts import UNTRUSTED, Prompt
from bomagent_agents.retrieval import Retriever
from bomagent_agents.runtimes.base import Dependencies, RunResult, model_info
from bomagent_agents.runtimes.variant_a import lines_to_items
from bomagent_agents.schemas import GroupedBom
from bomagent_agents.tools import TOOLS, CadTools, ToolError
from bomagent_bom.model import BomVersion, ParsedDesign, Requirements, Usage
from bomagent_bom.refdes import natural_key

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

SINGLE_AGENT = Prompt(
    "single_agent_bom",
    "1.0.0",
    "You are an engineer producing the bill of materials of an electronic medical device. "
    "Read every component with the CAD tools (all pages), group identical parts into "
    "lines, and for lines without a manufacturer part number search the knowledge base and "
    "choose an orderable part - use only part numbers that appear verbatim in search "
    "results, otherwise leave mpn empty. "
    + UNTRUSTED
    + ' Finish with JSON {"lines": [{"refdes", "quantity", "kind", "value", '
    '"value_normalized", "footprint", "package", "mpn", "manufacturer", "description", '
    '"dnp"}]} and nothing else.',
    "Design: {design_name}. Device requirements:\n<data>\n{requirements}\n</data>",
)


@dataclass
class LoopResult:
    text: str
    usage: Usage


class AgentLoop(Protocol):
    async def run(
        self,
        system: str,
        user: str,
        tools: dict[str, tuple[dict[str, Any], ToolHandler]],
        model: str,
    ) -> LoopResult: ...


class ResidencyError(RuntimeError):
    pass


def check_bedrock_eu(env: dict[str, str] | None = None) -> None:
    e = env if env is not None else dict(os.environ)
    if e.get("CLAUDE_CODE_USE_BEDROCK") != "1" or not e.get("AWS_REGION", "").startswith("eu-"):
        raise ResidencyError(
            "Claude Agent SDK adapter requires CLAUDE_CODE_USE_BEDROCK=1 and an EU AWS_REGION "
            "(ADR-0006: processing in the EU only)"
        )


class ClaudeSdkLoop:  # pragma: no cover - needs the SDK, the Claude Code CLI and Bedrock access
    """Thin wrapper over ``claude_agent_sdk`` (in-process MCP tools + ``query``)."""

    async def run(
        self,
        system: str,
        user: str,
        tools: dict[str, tuple[dict[str, Any], ToolHandler]],
        model: str,
    ) -> LoopResult:
        check_bedrock_eu()
        import claude_agent_sdk as sdk

        sdk_tools = []
        for name, (schema, handler) in tools.items():

            async def call(args: dict[str, Any], _h: ToolHandler = handler) -> dict[str, Any]:
                return {"content": [{"type": "text", "text": json.dumps(await _h(args))}]}

            sdk_tools.append(
                sdk.tool(name, schema.get("description", name), schema["parameters"])(call)
            )
        server = sdk.create_sdk_mcp_server(name="bom", version="1.0.0", tools=sdk_tools)
        options = sdk.ClaudeAgentOptions(
            system_prompt=system,
            mcp_servers={"bom": server},
            allowed_tools=[f"mcp__bom__{n}" for n in tools],
            model=model,
            max_turns=60,
        )
        text, usage = "", Usage()
        async for message in sdk.query(prompt=user, options=options):
            if type(message).__name__ == "ResultMessage":
                text = getattr(message, "result", "") or text
                u = getattr(message, "usage", None) or {}
                usage = Usage(
                    llm_calls=int(getattr(message, "num_turns", 1) or 1),
                    input_tokens=int(u.get("input_tokens", 0)),
                    output_tokens=int(u.get("output_tokens", 0)),
                    cached_input_tokens=int(u.get("cache_read_input_tokens", 0)),
                )
        return LoopResult(text, usage)


def build_tools(
    design: ParsedDesign, retriever: Retriever, k: int
) -> dict[str, tuple[dict[str, Any], ToolHandler]]:
    cad = CadTools(design)
    out: dict[str, tuple[dict[str, Any], ToolHandler]] = {}
    for spec in TOOLS:

        async def handler(args: dict[str, Any], _name: str = spec.name) -> dict[str, Any]:
            try:
                return cad.execute(_name, args)
            except ToolError as exc:
                return {"error": str(exc)}

        out[spec.name] = (spec.model_dump(), handler)

    async def search(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))[:500]
        hits = (await retriever.search_many([query], k))[0]
        return {
            "excerpts": [{"id": h.chunk_id, "source": h.title, "text": h.content} for h in hits]
        }

    out["search_kb"] = (
        {
            "name": "search_kb",
            "description": "Search component datasheets (ordering information, parameters).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        search,
    )
    return out


class ClaudeSdkVariantA:
    name = "A-sdk"

    def __init__(self, loop: AgentLoop | None = None) -> None:
        self.loop = loop or ClaudeSdkLoop()

    async def run(
        self,
        design: ParsedDesign,
        requirements: Requirements,
        config: RunConfig,
        deps: Dependencies,
        *,
        checkpointer: Any = None,
    ) -> RunResult:
        state = RunState(config)
        llm = AgentLLM(deps.chat, deps.model, state)  # provenance + cost helpers only
        system, user = SINGLE_AGENT.render(
            design_name=design.design_name, requirements=requirements.model_dump(mode="json")
        )
        try:
            with state.step("agent_loop", "llm", "single_agent") as s:
                res = await self.loop.run(
                    system,
                    user,
                    build_tools(design, deps.retriever, config.kb_top_k),
                    deps.model.gateway_model,
                )
                cost = deps.model.cost(res.usage.input_tokens, res.usage.output_tokens)
                await state.add_usage(res.usage.model_copy(update={"cost_eur": cost}))
                grouped = GroupedBom.model_validate(json.loads(res.text))
                items, problems = lines_to_items(grouped.lines, llm, "single_agent", SINGLE_AGENT)
                s.note(f"{len(items)} lines")
        except Exception as exc:
            state.usage = state.usage.model_copy(update={"wall_time_s": round(state.elapsed, 3)})
            return RunResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:1000],
                trace=state.trace,
                usage=state.usage,
                config=config,
                model=model_info(deps.model),
            )
        items = sorted(items, key=lambda i: natural_key(i.refdes[0]))
        items = [i.model_copy(update={"line": n}) for n, i in enumerate(items, start=1)]
        state.usage = state.usage.model_copy(update={"wall_time_s": round(state.elapsed, 3)})
        bom = BomVersion(
            design_name=design.design_name,
            variant=f"A-sdk:{deps.model.id}",
            items=items,
            findings=problems,
            usage=state.usage,
            kb_snapshot_id=config.kb_snapshot_id,
        )
        return RunResult(
            bom=bom,
            trace=state.trace,
            usage=state.usage,
            config=config,
            model=model_info(deps.model),
        )
