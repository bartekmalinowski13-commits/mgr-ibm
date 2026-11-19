"""Variant A - every step done by LLM agents (thesis baseline "100 % LLM").

Graph::

    extract_group (agent) -> select_mpn* (agent + RAG, fan-out, ALL lines)
        -> validate (agent) -> compose (agent) -> to BomVersion (structural only)

Code-side work is structural only: converting the agents' JSON into ``BomItem`` objects
(quantity as the agent stated it; malformed lines are dropped and reported, not repaired).
The same retrieval, models, MPN prompt, evidence-only MPN rule, budget and failure
handling as variant B are used, so differences are attributable to the architecture
(docs/thesis/ARCHITEKTURA_WARIANTOW.md). Input: the parser's component list (A's
extraction agent reads parsed components rather than raw CAD files - DECISIONS_LOG).
"""

from __future__ import annotations

import time
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from bomagent_agents import resume
from bomagent_agents.contracts import RunInput, RunOutput
from bomagent_agents.runtime_base import AgentContext, agent_provenance, line_key
from bomagent_agents.schemas import GroupedLines, LineOut, ValidationOut
from bomagent_agents.variant_b import (
    apply_choices,
    choose_mpn,
    finish,
    merge_choices,
    record_rejections,
)
from bomagent_bom.grouping import MPN_FIELDS
from bomagent_bom.model import (
    BomItem,
    Finding,
    ParsedDesign,
    Provenance,
    Requirements,
    Severity,
)
from bomagent_bom.packages import package_from_footprint
from bomagent_bom.refdes import kind_of

LINE_KEYS = (
    "refdes",
    "quantity",
    "value",
    "footprint",
    "mpn",
    "manufacturer",
    "dnp",
    "description",
)


async def llm_validate(
    ctx: AgentContext, items: list[BomItem], requirements: Requirements
) -> list[Finding]:
    """Variant A's validation: the validator agent reviews every line (no rule pack)."""
    lines = [{k: getattr(i, k) for k in LINE_KEYS} | {"line": i.line} for i in items]
    result = await ctx.guarded(
        "validate",
        lambda: ctx.ask(
            "validate",
            {"lines": lines, "requirements": requirements.model_dump(mode="json")},
            ValidationOut,
            max_tokens=8_000,
        ),
        None,
    )
    if result is None:
        return []
    return [
        Finding(
            rule_id="agent.validate",
            severity=Severity(f.severity),
            message=f.message,
            refdes=f.refdes,
            field=f.field,
        )
        for f in result[0].findings
    ]


class AState(TypedDict, total=False):
    items: list[dict[str, Any]]
    choices: Annotated[list[dict[str, Any]] | None, merge_choices]
    findings: list[dict[str, Any]]


def lines_to_items(
    ctx: AgentContext | None, lines: list[LineOut], provenance: Provenance, step: str
) -> list[BomItem]:
    items: list[BomItem] = []
    for line in lines:
        try:
            items.append(
                BomItem(
                    line=len(items) + 1,
                    refdes=line.refdes,
                    quantity=line.quantity if line.quantity is not None else len(line.refdes),
                    kind=kind_of(line.refdes[0]) if line.refdes else "other",
                    value=line.value,
                    footprint=line.footprint,
                    package=package_from_footprint(line.footprint),
                    mpn=line.mpn,
                    manufacturer=line.manufacturer,
                    description=line.description,
                    dnp=line.dnp,
                    provenance={
                        "item": provenance,
                        "quantity": provenance,
                        "value": provenance,
                        "footprint": provenance,
                    },
                )
            )
        except ValueError as exc:
            if ctx is not None:
                ctx.issues.append(
                    Finding(
                        rule_id="agent.malformed_line",
                        severity=Severity.ERROR,
                        refdes=[r for r in line.refdes if r][:20],
                        message=f"{step}: line dropped ({type(exc).__name__})",
                    )
                )
    return items


def attribute_mpns(
    items: list[BomItem],
    design: ParsedDesign,
    agent: Provenance,
    previous: list[BomItem] | None = None,
) -> list[BomItem]:
    """Record where every MPN of agent-written lines comes from (review I6).

    * the same MPN the line (same designator set) had before keeps that provenance
      (``mpn_select`` with its citations, or the parser),
    * an MPN that every component of the line carries in the design file is the parser's,
    * anything else was decided by ``agent`` (extract_group, compose, submit_bom).

    So every agent MPN counts in the H2 denominator (METODYKA §2), as in variant B."""
    parser = Provenance.from_parser(design.source_format)
    in_file = {c.refdes: c.field(*MPN_FIELDS).strip().upper() for c in design.components}
    before = {line_key(i.refdes): i for i in previous or []}
    out: list[BomItem] = []
    for item in items:
        prov = {k: v for k, v in item.provenance.items() if k not in {"mpn", "manufacturer"}}
        if item.mpn:
            mpn = item.mpn.strip().upper()
            old = before.get(line_key(item.refdes))
            if old is not None and old.mpn.strip().upper() == mpn and "mpn" in old.provenance:
                source = old.provenance["mpn"]
            elif all(in_file.get(r) == mpn for r in item.refdes):
                source = parser
            else:
                source = agent
            prov |= {"mpn": source, "manufacturer": source}
        out.append(item.model_copy(update={"provenance": prov}))
    return out


class LangGraphVariantA:
    name = "langgraph_a"

    def __init__(self, ctx_factory: Any) -> None:
        self._ctx_factory = ctx_factory

    def _graph(self, ctx: AgentContext, run: RunInput) -> Any:
        async def extract_group(state: AState) -> AState:
            comps = [c.model_dump(mode="json") for c in run.design.components]
            result = await ctx.guarded(
                "extract_group",
                lambda: ctx.ask(
                    "extract_group", {"components": comps}, GroupedLines, max_tokens=16_000
                ),
                None,
            )
            if result is None:
                return {"items": []}
            out, prompt, model = result
            prov = agent_provenance("extract_group", prompt, model)
            items = lines_to_items(ctx, out.lines, prov, "extract_group")
            items = attribute_mpns(ctx.guard_mpns(items, "extract_group"), run.design, prov)
            return {"items": [i.model_dump(mode="json") for i in items]}

        def fan_out(state: AState) -> list[Send] | str:
            todo = [i for i in state["items"] if not i["dnp"]]
            return [Send("select_mpn", {"item": i}) for i in todo] or "validate"

        async def select_mpn(payload: dict[str, Any]) -> AState:
            item = BomItem.model_validate(payload["item"])
            choice = await ctx.guarded(
                f"select_mpn:{item.refdes[0]}", lambda: choose_mpn(ctx, item), None
            )
            return {"choices": [choice] if choice else []}

        async def validate_node(state: AState) -> AState:
            record_rejections(ctx, state.get("choices") or [])
            items = apply_choices(state["items"], state.get("choices"))
            findings = await llm_validate(ctx, items, run.requirements)
            return {
                "items": [i.model_dump(mode="json") for i in items],
                "choices": None,  # applied: clear, so finish does not apply them again
                "findings": [f.model_dump(mode="json") for f in findings],
            }

        async def compose(state: AState) -> AState:
            if ctx.status != "completed":
                return {}
            lines = [{k: i[k] for k in LINE_KEYS} for i in state["items"]]
            result = await ctx.guarded(
                "compose",
                lambda: ctx.ask(
                    "compose",
                    {"lines": lines, "findings": state["findings"]},
                    GroupedLines,
                    max_tokens=16_000,
                ),
                None,
            )
            if result is None:
                return {}  # keep the validated items
            out, prompt, model = result
            prov = agent_provenance("compose", prompt, model)
            composed = ctx.guard_mpns(lines_to_items(ctx, out.lines, prov, "compose"), "compose")
            previous = [BomItem.model_validate(i) for i in state["items"]]
            # an unchanged MPN keeps its citations; a changed or added one is compose's
            items = attribute_mpns(composed, run.design, prov, previous)
            return {"items": [i.model_dump(mode="json") for i in items]}

        g = StateGraph(AState)
        g.add_node("extract_group", extract_group)
        g.add_node("select_mpn", select_mpn)  # type: ignore[arg-type]  # Send payload
        g.add_node("validate", validate_node)
        g.add_node("compose", compose)
        g.add_edge(START, "extract_group")
        g.add_conditional_edges("extract_group", fan_out, ["select_mpn", "validate"])
        g.add_edge("select_mpn", "validate")
        g.add_edge("validate", "compose")
        g.add_edge("compose", END)
        return g.compile(checkpointer=ctx.checkpointer or InMemorySaver())

    async def run(self, run: RunInput) -> RunOutput:
        ctx: AgentContext = self._ctx_factory(run)
        start = time.perf_counter()
        graph = self._graph(ctx, run)
        config: dict[str, Any] = {
            "configurable": {"thread_id": str(run.run_id)},
            "max_concurrency": run.config.concurrency,
        }
        # ``None`` continues from the last checkpoint (resume after a crash, ARCH-05)
        state = await graph.ainvoke(await resume.begin(ctx, graph, config), config=config)
        return finish(ctx, run, state, self.name, "A", start)
