"""Variant A - multi-agent system based only on LLMs.

LangGraph graph::

    plan -> extract (tool loop over CAD tools) -> group -> select --> validate --+--> compose
                                                            ^                   |
                                                            +--- reselect <-----+ (max N)

Every step is performed by an agent; the only deterministic parts are the read-only CAD
tools that the extraction agent calls (they expose the parser output) and the mapping of
the agents' JSON into the shared ``BomVersion`` schema.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from bomagent_agents.context import AgentLLM, AgentOutputError, RunConfig, RunState
from bomagent_agents.prompts import COMPOSE, EXTRACT, GROUP, ORCHESTRATOR, VALIDATE, Prompt
from bomagent_agents.runtimes.base import (
    Dependencies,
    RunResult,
    apply_selection,
    line_payload,
    model_info,
    select_parts,
)
from bomagent_agents.schemas import (
    ExtractedComponents,
    GroupedBom,
    GroupedLine,
    Plan,
    ValidationVerdict,
)
from bomagent_agents.tools import TOOLS, CadTools, ToolError
from bomagent_bom.model import (
    BomItem,
    BomVersion,
    Finding,
    ParsedDesign,
    Requirements,
    Severity,
    Usage,
)
from bomagent_bom.refdes import natural_key
from bomagent_llm.chat import ChatMessage

AGENT_RULE = "agent.validate"
AGENT_FIELDS = ("item", "quantity", "value", "footprint", "kind", "mpn", "manufacturer")


class _State(TypedDict, total=False):
    plan: dict[str, Any]
    components: list[dict[str, Any]]
    items: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    reselect: list[int]
    feedback: dict[str, str]
    iteration: int


def _items(st: _State) -> list[BomItem]:
    return [BomItem.model_validate(i) for i in st.get("items", [])]


def _dump(items: list[BomItem]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in items]


def lines_to_items(
    lines: list[GroupedLine], llm: AgentLLM, agent: str, prompt: Prompt
) -> tuple[list[BomItem], list[Finding]]:
    """Map agent JSON to BOM lines. Lines that violate the BOM schema (duplicate designators)
    are kept with duplicates removed and reported - the variant is not silently repaired."""
    prov = llm.provenance(agent, prompt)
    items: list[BomItem] = []
    problems: list[Finding] = []
    for n, ln in enumerate(lines, start=1):
        refs = list(dict.fromkeys(r.strip() for r in ln.refdes if r.strip()))
        if len(refs) != len(ln.refdes):
            problems.append(
                Finding(
                    rule_id="schema.coerced",
                    severity=Severity.ERROR,
                    message="agent output repeated a designator within one line",
                    refdes=refs,
                    line=n,
                )
            )
        if not refs:
            continue
        quantity = ln.quantity if ln.quantity > 0 else len(refs)
        items.append(
            BomItem(
                line=n,
                refdes=refs,
                quantity=quantity,
                kind=ln.kind or "other",
                value=ln.value,
                value_normalized=ln.value_normalized,
                footprint=ln.footprint,
                package=ln.package,
                manufacturer=ln.manufacturer,
                mpn=ln.mpn,
                description=ln.description,
                dnp=ln.dnp,
                provenance=dict.fromkeys(AGENT_FIELDS, prov),
            )
        )
    return items, problems


class VariantA:
    name = "A"

    async def run(  # noqa: PLR0915 - graph nodes are closures over the run's state
        self,
        design: ParsedDesign,
        requirements: Requirements,
        config: RunConfig,
        deps: Dependencies,
        *,
        checkpointer: Any = None,
    ) -> RunResult:
        state = RunState(config)
        llm = AgentLLM(deps.chat, deps.model, state)
        tools = CadTools(design)
        req = requirements.model_dump(mode="json")
        coerced: list[Finding] = []

        async def plan(_: _State) -> _State:
            with state.step("plan", "llm", "orchestrator") as s:
                summary = {
                    "design": design.design_name,
                    "format": design.source_format,
                    "components": len(design.components),
                    "sheets": design.sheets,
                }
                p = await llm.structured(
                    ORCHESTRATOR, "orchestrator", Plan, summary=summary, requirements=req
                )
                s.note(f"{len(p.steps)} planned steps")
            return {"plan": p.model_dump(), "iteration": 0}

        async def extract(_: _State) -> _State:
            with state.step("extract", "llm", "extractor") as s:
                system, user = EXTRACT.render(design_name=design.design_name, sheets=design.sheets)
                messages = [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ]
                result: ExtractedComponents | None = None
                for _round in range(config.budget.max_tool_rounds):
                    request = llm._request(
                        EXTRACT, "extractor", messages, ExtractedComponents, TOOLS
                    )
                    resp = await llm.call(request)
                    if resp.tool_calls:
                        messages.append(
                            ChatMessage(
                                role="assistant",
                                content=resp.content or None,
                                tool_calls=resp.tool_calls,
                            )
                        )
                        for call in resp.tool_calls:
                            try:
                                out: dict[str, Any] = tools.execute(call.name, call.arguments)
                            except ToolError as exc:
                                out = {"error": str(exc)}
                            await state.add_usage(Usage(tool_calls=1))
                            messages.append(
                                ChatMessage(
                                    role="tool",
                                    tool_call_id=call.id,
                                    name=call.name,
                                    content=json.dumps(out, ensure_ascii=False),
                                )
                            )
                        continue
                    result = await _parse_or_retry(llm, messages, resp.content)
                    break
                if result is None:
                    raise AgentOutputError(
                        f"extractor: no answer after {config.budget.max_tool_rounds} tool rounds"
                    )
                s.note(f"{len(result.components)} components via {tools.calls} tool calls")
            return {"components": [c.model_dump() for c in result.components]}

        async def group(st: _State) -> _State:
            with state.step("group", "llm", "grouper") as s:
                g = await llm.structured(
                    GROUP, "grouper", GroupedBom, components=st.get("components", [])
                )
                items, problems = lines_to_items(g.lines, llm, "grouper", GROUP)
                coerced.extend(problems)
                s.note(f"{len(items)} lines")
            return {
                "items": _dump(items),
                "reselect": [i for i, it in enumerate(items) if not it.mpn and not it.dnp],
            }

        async def select(st: _State) -> _State:
            items = _items(st)
            targets = st.get("reselect", [])
            feedback = {int(k): v for k, v in st.get("feedback", {}).items()}
            with state.step("select", "llm", "selector") as s:
                chosen = await select_parts(
                    items,
                    targets,
                    requirements,
                    llm,
                    deps.retriever,
                    state,
                    agent="selector",
                    feedback=feedback,
                )
                for idx, (sel, hits) in chosen.items():
                    items[idx] = apply_selection(items[idx], sel, hits, llm, "selector")
                s.note(
                    f"selected parts for {sum(1 for v in chosen.values() if v[0].mpn)}"
                    f"/{len(targets)} lines"
                )
            return {"items": _dump(items)}

        async def validate(st: _State) -> _State:
            items = _items(st)
            with state.step("validate", "llm", "validator") as s:
                verdict = await llm.structured(
                    VALIDATE,
                    "validator",
                    ValidationVerdict,
                    lines=[line_payload(i) for i in items],
                    requirements=req,
                )
                by_ref = {r: idx for idx, it in enumerate(items) for r in it.refdes}
                reselect: list[int] = []
                feedback: dict[str, str] = {}
                for issue in verdict.issues:
                    if not issue.reselect:
                        continue
                    for r in issue.refdes:
                        if r in by_ref and by_ref[r] not in reselect:
                            reselect.append(by_ref[r])
                            feedback[str(by_ref[r])] = issue.message
                s.note(f"{len(verdict.issues)} issues, {len(reselect)} lines to reselect")
            return {
                "issues": [i.model_dump() for i in verdict.issues],
                "reselect": reselect,
                "feedback": feedback,
            }

        def after_validate(st: _State) -> str:
            if st.get("reselect") and st.get("iteration", 0) < config.budget.max_repair_iterations:
                return "reselect"
            return "compose"

        async def bump(st: _State) -> _State:
            return {"iteration": st.get("iteration", 0) + 1}

        async def compose(st: _State) -> _State:
            items = _items(st)
            with state.step("compose", "llm", "composer") as s:
                composed = await llm.structured(
                    COMPOSE, "composer", GroupedBom, lines=[line_payload(i) for i in items]
                )
                final, problems = lines_to_items(composed.lines, llm, "composer", COMPOSE)
                coerced.extend(problems)
                # keep the selector's provenance (with citations) where the MPN is unchanged
                before = {it.refdes[0]: it for it in items}
                merged = []
                for line in final:
                    prev = before.get(line.refdes[0])
                    if prev is not None and prev.mpn == line.mpn and "mpn" in prev.provenance:
                        prov = dict(line.provenance)
                        prov["mpn"] = prev.provenance["mpn"]
                        if "manufacturer" in prev.provenance:
                            prov["manufacturer"] = prev.provenance["manufacturer"]
                        line = line.model_copy(update={"provenance": prov})  # noqa: PLW2901
                    merged.append(line)
                s.note(f"{len(merged)} final lines")
            return {"items": _dump(merged)}

        # LangGraph's overloads do not model closures returning partial TypedDicts
        builder: Any = StateGraph(_State)
        for name, fn in (
            ("plan", plan),
            ("extract", extract),
            ("group", group),
            ("select", select),
            ("validate", validate),
            ("reselect", bump),
            ("compose", compose),
        ):
            builder.add_node(name, fn)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "extract")
        builder.add_edge("extract", "group")
        builder.add_edge("group", "select")
        builder.add_edge("select", "validate")
        builder.add_conditional_edges(
            "validate", after_validate, {"reselect": "reselect", "compose": "compose"}
        )
        builder.add_edge("reselect", "select")
        builder.add_edge("compose", END)
        graph = builder.compile(checkpointer=checkpointer)

        try:
            final = await graph.ainvoke(
                {},
                config={"configurable": {"thread_id": str(config.run_id)}, "recursion_limit": 50},
            )
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

        items = sorted(_items(cast(_State, final)), key=lambda i: natural_key(i.refdes[0]))
        items = [i.model_copy(update={"line": n}) for n, i in enumerate(items, start=1)]
        by_ref = {r: it.line for it in items for r in it.refdes}
        findings = [
            Finding(
                rule_id=AGENT_RULE,
                severity=Severity(i["severity"]),
                message=i["message"],
                refdes=i["refdes"],
                field=i.get("field"),
                line=by_ref.get(i["refdes"][0]) if i["refdes"] else None,
                rule_pack="agents-a",
                rule_pack_version=VALIDATE.version,
            )
            for i in final.get("issues", [])
        ] + coerced
        state.usage = state.usage.model_copy(update={"wall_time_s": round(state.elapsed, 3)})
        bom = BomVersion(
            design_name=design.design_name,
            variant=f"A:{deps.model.id}",
            items=items,
            findings=sorted(findings, key=lambda f: (f.line or 0, f.rule_id)),
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


async def _parse_or_retry(
    llm: AgentLLM, messages: list[ChatMessage], content: str
) -> ExtractedComponents:
    try:
        return ExtractedComponents.model_validate(json.loads(content or "null"))
    except (json.JSONDecodeError, ValueError):
        retry = [
            *messages,
            ChatMessage(role="assistant", content=content),
            ChatMessage(
                role="user", content='Answer with the final JSON {"components": [...]} only.'
            ),
        ]
        return await llm.structured(EXTRACT, "extractor", ExtractedComponents, messages=retry)
