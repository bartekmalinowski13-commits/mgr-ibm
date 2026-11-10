"""Variant A - every step done by LLM agents (thesis baseline "100 % LLM").

Graph::

    extract_group (agent) -> select_mpn* (agent + RAG, fan-out, ALL lines)
        -> validate (agent) -> compose (agent) -> to BomVersion (structural only)

The only code-side work is structural: converting the agents' JSON into ``BomItem``
objects (with ``quantity`` exactly as the agent stated it) and recording provenance.
The same retrieval, models and MPN prompt as variant B are used, so differences are
attributable to the architecture (docs/thesis/ARCHITEKTURA_WARIANTOW.md).
"""

from __future__ import annotations

import operator
import time
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from bomagent_agents.contracts import BudgetExceededError, RunInput, RunOutput
from bomagent_agents.runtime_base import AgentContext, agent_provenance
from bomagent_agents.schemas import GroupedLines, LineOut, ValidationOut
from bomagent_agents.variant_b import apply_choice, choose_mpn
from bomagent_bom.model import BomItem, BomVersion, Finding, Severity
from bomagent_bom.packages import package_from_footprint
from bomagent_bom.refdes import kind_of


class AState(TypedDict, total=False):
    items: list[dict[str, Any]]
    choices: Annotated[list[dict[str, Any]], operator.add]
    findings: list[dict[str, Any]]


def lines_to_items(lines: list[LineOut], provenance: Any) -> list[BomItem]:
    items: list[BomItem] = []
    for n, line in enumerate(lines, start=1):
        refs = [r for r in dict.fromkeys(line.refdes) if r]
        if not refs:
            continue
        try:
            items.append(
                BomItem(
                    line=n,
                    refdes=refs,
                    quantity=max(1, line.quantity if line.quantity is not None else len(refs)),
                    kind=kind_of(refs[0]),
                    value=line.value,
                    footprint=line.footprint,
                    package=package_from_footprint(line.footprint),
                    mpn=line.mpn,
                    manufacturer=line.manufacturer,
                    dnp=line.dnp,
                    provenance={
                        "item": provenance,
                        "quantity": provenance,
                        "value": provenance,
                        "footprint": provenance,
                    },
                )
            )
        except ValueError:
            continue  # malformed agent output line (e.g. invalid designator) is dropped
    return items


class LangGraphVariantA:
    name = "langgraph_a"

    def __init__(self, ctx_factory: Any) -> None:
        self._ctx_factory = ctx_factory

    def _graph(self, ctx: AgentContext, run: RunInput) -> Any:
        async def extract_group(state: AState) -> AState:
            comps = [c.model_dump(mode="json") for c in run.design.components]
            out, prompt, model = await ctx.step(
                "extract_group",
                lambda: ctx.ask("extract_group", {"components": comps}, GroupedLines),
            )
            items = lines_to_items(out.lines, agent_provenance("extract_group", prompt, model))
            return {"items": [i.model_dump(mode="json") for i in items]}

        def fan_out(state: AState) -> list[Send] | str:
            todo = [i for i in state["items"] if not i["dnp"]]
            return [Send("select_mpn", {"item": i}) for i in todo] or "validate"

        async def select_mpn(payload: dict[str, Any]) -> AState:
            item = BomItem.model_validate(payload["item"])
            choice = await ctx.step(f"select_mpn:{item.refdes[0]}", lambda: choose_mpn(ctx, item))
            return {"choices": [choice]}

        async def validate_node(state: AState) -> AState:
            by_line = {c["line"]: c for c in state.get("choices", [])}
            items = [
                apply_choice(BomItem.model_validate(i), by_line[i["line"]])
                if i["line"] in by_line
                else BomItem.model_validate(i)
                for i in state["items"]
            ]
            lines = [
                {
                    "line": i.line,
                    "refdes": i.refdes,
                    "quantity": i.quantity,
                    "value": i.value,
                    "footprint": i.footprint,
                    "mpn": i.mpn,
                    "manufacturer": i.manufacturer,
                    "dnp": i.dnp,
                }
                for i in items
            ]
            out, _, _ = await ctx.step(
                "validate",
                lambda: ctx.ask(
                    "validate",
                    {"lines": lines, "requirements": run.requirements.model_dump(mode="json")},
                    ValidationOut,
                ),
            )
            findings = [
                Finding(
                    rule_id="agent.validate",
                    severity=Severity(f.severity),
                    message=f.message,
                    refdes=f.refdes,
                    field=f.field,
                )
                for f in out.findings
            ]
            return {
                "items": [i.model_dump(mode="json") for i in items],
                "findings": [f.model_dump(mode="json") for f in findings],
            }

        async def compose(state: AState) -> AState:
            lines = [
                {
                    k: i[k]
                    for k in (
                        "refdes",
                        "quantity",
                        "value",
                        "footprint",
                        "mpn",
                        "manufacturer",
                        "dnp",
                    )
                }
                for i in state["items"]
            ]
            out, prompt, model = await ctx.step(
                "compose",
                lambda: ctx.ask(
                    "compose", {"lines": lines, "findings": state["findings"]}, GroupedLines
                ),
            )
            prov = agent_provenance("compose", prompt, model)
            previous = {tuple(i["refdes"]): BomItem.model_validate(i) for i in state["items"]}
            items = []
            for composed in lines_to_items(out.lines, prov):
                item = composed
                before = previous.get(tuple(item.refdes))
                if before is not None and "mpn" in before.provenance:  # keep MPN citations
                    item = item.model_copy(
                        update={
                            "provenance": {
                                **item.provenance,
                                "mpn": before.provenance["mpn"],
                                "manufacturer": before.provenance["mpn"],
                            }
                        }
                    )
                items.append(item)
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
        return g.compile(checkpointer=InMemorySaver())

    async def run(self, run: RunInput) -> RunOutput:
        ctx: AgentContext = self._ctx_factory(run)
        graph = self._graph(ctx, run)
        start = time.perf_counter()
        status: Literal["completed", "budget_exceeded", "failed"] = "completed"
        config = {
            "configurable": {"thread_id": str(run.run_id)},
            "max_concurrency": run.config.concurrency,
        }
        try:
            state = await graph.ainvoke({}, config=config)
        except BudgetExceededError as exc:
            status = "budget_exceeded"
            state = dict(graph.get_state(config).values or {})
            state.setdefault("findings", []).append(
                Finding(rule_id="run.budget", severity=Severity.ERROR, message=str(exc)).model_dump(
                    mode="json"
                )
            )
        usage = ctx.budget.usage.model_copy(update={"wall_time_s": time.perf_counter() - start})
        bom = BomVersion(
            id=run.run_id,
            design_name=run.design.design_name,
            variant="A",
            items=[BomItem.model_validate(i) for i in state.get("items", [])],
            findings=[Finding.model_validate(f) for f in state.get("findings", [])],
            usage=usage,
            kb_snapshot_id=run.config.kb_snapshot_id,
        )
        return RunOutput(
            run_id=run.run_id,
            runtime=self.name,
            bom=bom,
            trace=ctx.trace,
            usage=usage,
            status=status,
        )
