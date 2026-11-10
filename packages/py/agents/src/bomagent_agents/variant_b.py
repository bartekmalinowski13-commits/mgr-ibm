"""Variant B - hybrid: deterministic components + LLM agents only where needed.

Graph (LangGraph)::

    normalize_group (rules) -> select_mpn* (agent + RAG, fan-out, only lines without MPN)
        -> validate (rule pack) -> repair (agent, <= N iterations, only on errors)
        -> assemble (deterministic generator)

Every field keeps its provenance: grouping/quantity from the rule ``bom.normalize_group``,
MPNs chosen by the agent with model, prompt version and cited KB chunks.
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
from bomagent_agents.schemas import MpnChoice, RepairOut
from bomagent_bom.grouping import group_components, renumber
from bomagent_bom.model import BomItem, BomVersion, Finding, KbCitation, Severity
from bomagent_bom.packages import package_from_footprint
from bomagent_rules import DEFAULT_PACK, validate

MPN_KINDS_SKIPPED = {"test_point", "mechanical"}


class BState(TypedDict, total=False):
    items: list[dict[str, Any]]
    choices: Annotated[list[dict[str, Any]], operator.add]
    findings: list[dict[str, Any]]
    iterations: int


def mpn_query(item: BomItem) -> str:
    parts = [item.value_normalized or item.value, item.package or "", item.kind.replace("_", " ")]
    if item.description:
        parts.append(item.description)
    # bias retrieval towards ordering tables, where purchasable part numbers are listed
    parts.append("ordering information part number")
    return " ".join(p for p in parts if p)


async def choose_mpn(ctx: AgentContext, item: BomItem) -> dict[str, Any]:
    """Agent step shared by both variants: retrieve evidence, let the model pick an MPN
    among the evidence candidates, keep citations for provenance."""
    (evidence,) = await ctx.retriever.evidence([mpn_query(item)], ctx.config.kb_k)
    payload = {
        "line": {
            "line": item.line,
            "refdes": item.refdes,
            "kind": item.kind,
            "value": item.value,
            "value_normalized": item.value_normalized,
            "footprint": item.footprint,
            "package": item.package,
            "description": item.description,
        },
        "requirements": ctx.requirements.model_dump(mode="json"),
        "candidates": [
            {"mpn": c.mpn, "context": c.context, "chunk_id": c.chunk_id, "document": c.document}
            for c in evidence.candidates
        ],
    }
    choice, prompt, model = await ctx.ask("mpn_select", payload, MpnChoice, knowledge=evidence)
    allowed = {c.mpn.upper() for c in evidence.candidates}
    by_chunk = {str(h.chunk_id): h for h in evidence.hits}
    mpn = choice.mpn if choice.mpn.upper() in allowed else ""  # never accept an invented MPN
    citations = [by_chunk[cid].citation() for cid in choice.citation_chunk_ids if cid in by_chunk]
    prov = agent_provenance("mpn_select", prompt, model, choice.rationale, citations)
    return {
        "line": item.line,
        "mpn": mpn,
        "manufacturer": choice.manufacturer if mpn else "",
        "provenance": prov.model_dump(mode="json"),
        "rejected": choice.mpn if choice.mpn and not mpn else "",
    }


def apply_choice(item: BomItem, choice: dict[str, Any]) -> BomItem:
    if not choice["mpn"]:
        return item
    from bomagent_bom.model import Provenance

    prov = Provenance.model_validate(choice["provenance"])
    return item.model_copy(
        update={
            "mpn": choice["mpn"],
            "manufacturer": choice["manufacturer"] or item.manufacturer,
            "provenance": {**item.provenance, "mpn": prov, "manufacturer": prov},
        }
    )


class LangGraphVariantB:
    name = "langgraph_b"

    def __init__(self, ctx_factory: Any) -> None:
        self._ctx_factory = ctx_factory

    def _graph(self, ctx: AgentContext, run: RunInput) -> Any:
        async def normalize_group(state: BState) -> BState:
            items = await ctx.step("normalize_group", _async(lambda: group_components(run.design)))
            return {"items": [i.model_dump(mode="json") for i in items], "iterations": 0}

        def fan_out(state: BState) -> list[Send] | str:
            todo = [
                i
                for i in state["items"]
                if not i["mpn"] and not i["dnp"] and i["kind"] not in MPN_KINDS_SKIPPED
            ]
            return [Send("select_mpn", {"item": i}) for i in todo] or "validate"

        async def select_mpn(payload: dict[str, Any]) -> BState:
            item = BomItem.model_validate(payload["item"])
            choice = await ctx.step(f"select_mpn:{item.refdes[0]}", lambda: choose_mpn(ctx, item))
            return {"choices": [choice]}

        async def validate_node(state: BState) -> BState:
            by_line = {c["line"]: c for c in state.get("choices", [])}
            items = [
                apply_choice(BomItem.model_validate(i), by_line[i["line"]])
                if i["line"] in by_line
                else BomItem.model_validate(i)
                for i in state["items"]
            ]
            report = await ctx.step("validate", _async(lambda: validate(items, run.requirements)))
            return {
                "items": [i.model_dump(mode="json") for i in items],
                "findings": [f.model_dump(mode="json") for f in report.findings],
            }

        def needs_repair(state: BState) -> str:
            errors = [f for f in state["findings"] if f["severity"] == "error"]
            if errors and state.get("iterations", 0) < ctx.config.max_repair_iterations:
                return "repair"
            return "assemble"

        async def repair(state: BState) -> BState:
            errors = [f for f in state["findings"] if f["severity"] == "error"]
            affected = {f["line"] for f in errors}
            lines = [i for i in state["items"] if i["line"] in affected]
            out, prompt, model = await ctx.step(
                "repair", lambda: ctx.ask("repair", {"lines": lines, "findings": errors}, RepairOut)
            )
            items = [BomItem.model_validate(i) for i in state["items"]]
            prov = agent_provenance("repair", prompt, model)
            for fix in out.fixes:
                for n, item in enumerate(items):
                    if item.line == fix.line and fix.field in {
                        "footprint",
                        "value",
                        "mpn",
                        "manufacturer",
                    }:
                        update: dict[str, Any] = {
                            fix.field: fix.new_value,
                            "provenance": {**item.provenance, fix.field: prov},
                        }
                        if fix.field == "footprint":
                            update["package"] = package_from_footprint(fix.new_value)
                        items[n] = item.model_copy(update=update)
            report = validate(items, run.requirements)
            return {
                "items": [i.model_dump(mode="json") for i in items],
                "findings": [f.model_dump(mode="json") for f in report.findings],
                "iterations": state.get("iterations", 0) + 1,
            }

        async def assemble(state: BState) -> BState:
            return {
                "items": [
                    i.model_dump(mode="json")
                    for i in renumber([BomItem.model_validate(i) for i in state["items"]])
                ]
            }

        g = StateGraph(BState)
        g.add_node("normalize_group", normalize_group)
        g.add_node("select_mpn", select_mpn)  # type: ignore[arg-type]  # Send payload
        g.add_node("validate", validate_node)
        g.add_node("repair", repair)
        g.add_node("assemble", assemble)
        g.add_edge(START, "normalize_group")
        g.add_conditional_edges("normalize_group", fan_out, ["select_mpn", "validate"])
        g.add_edge("select_mpn", "validate")
        g.add_conditional_edges("validate", needs_repair, ["repair", "assemble"])
        g.add_conditional_edges("repair", needs_repair, ["repair", "assemble"])
        g.add_edge("assemble", END)
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
            state = graph.get_state(config).values or {}
            state.setdefault("findings", []).append(
                Finding(rule_id="run.budget", severity=Severity.ERROR, message=str(exc)).model_dump(
                    mode="json"
                )
            )
        items = [BomItem.model_validate(i) for i in state.get("items", [])]
        findings = [Finding.model_validate(f) for f in state.get("findings", [])]
        usage = ctx.budget.usage.model_copy(update={"wall_time_s": time.perf_counter() - start})
        bom = BomVersion(
            id=run.run_id,
            design_name=run.design.design_name,
            variant="B",
            items=items,
            findings=findings,
            usage=usage,
            kb_snapshot_id=run.config.kb_snapshot_id,
            rule_pack=DEFAULT_PACK.id,
            rule_pack_version=DEFAULT_PACK.version,
        )
        return RunOutput(
            run_id=run.run_id,
            runtime=self.name,
            bom=bom,
            trace=ctx.trace,
            usage=usage,
            status=status,
        )


def _async(fn: Any) -> Any:
    async def wrapper() -> Any:
        return fn()

    return wrapper


__all__ = ["KbCitation", "LangGraphVariantB", "apply_choice", "choose_mpn", "mpn_query"]
