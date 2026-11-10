"""Variant B - hybrid multi-agent system (LLM + deterministic components).

LangGraph graph::

    group (rules) -> select (LLM, only unresolved lines) -> validate (rules) --+--> generate (rules)
                                                     ^                       |
                                                     +---- repair (LLM) <----+  (errors on
                                                                                 LLM-decided
                                                                                 fields, max N)

Parsing, normalisation, grouping, quantities, validation and BOM assembly are
deterministic; the LLM is used where interpretation is needed: choosing a concrete part
for a line without an MPN and repairing a choice that a rule rejected.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from bomagent_agents.context import AgentLLM, RunConfig, RunState
from bomagent_agents.prompts import REPAIR, excerpts_block
from bomagent_agents.retrieval import norm_mpn
from bomagent_agents.runtimes.base import (
    Dependencies,
    RunResult,
    apply_selection,
    line_payload,
    line_query,
    model_info,
    select_parts,
)
from bomagent_agents.schemas import RepairResult
from bomagent_bom.grouping import group_components, renumber
from bomagent_bom.model import (
    BomItem,
    BomVersion,
    Finding,
    ParsedDesign,
    ProvenanceKind,
    Requirements,
    Severity,
)
from bomagent_rules import DEFAULT_PACK, RuleContext, run_pack

AGENTS_PACK = "agents-b"
AGENTS_PACK_VERSION = "1.0.0"
KB_RULE = "kb.mpn_known"


class _State(TypedDict, total=False):
    items: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    unresolved: list[int]
    repair_targets: list[int]
    iteration: int


def _items(state: _State) -> list[BomItem]:
    return [BomItem.model_validate(i) for i in state.get("items", [])]


def _dump(items: list[BomItem]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in items]


def _llm_decided(item: BomItem, field: str = "mpn") -> bool:
    prov = item.provenance.get(field)
    return prov is not None and prov.kind == ProvenanceKind.AGENT


class VariantB:
    name = "B"

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
        retriever = deps.retriever
        known: set[str] = set()

        async def group(_: _State) -> _State:
            with state.step("group", "rule", "normalizer") as s:
                items = group_components(design)
                unresolved = [i for i, it in enumerate(items) if not it.mpn and not it.dnp]
                s.note(f"{len(items)} lines, {len(unresolved)} without MPN")
            return {"items": _dump(items), "unresolved": unresolved, "iteration": 0}

        async def select(st: _State) -> _State:
            items = _items(st)
            targets = st.get("unresolved", [])
            with state.step("select", "llm", "selector") as s:
                chosen = await select_parts(
                    items, targets, requirements, llm, retriever, state, agent="selector"
                )
                for idx, (sel, hits) in chosen.items():
                    items[idx] = apply_selection(items[idx], sel, hits, llm, "selector")
                s.note(
                    f"selected parts for {sum(1 for v in chosen.values() if v[0].mpn)}"
                    f"/{len(targets)} lines"
                )
            return {"items": _dump(items)}

        async def validate(st: _State) -> _State:
            nonlocal known
            items = _items(st)
            with state.step("validate", "rule", "validator") as s:
                report = run_pack(DEFAULT_PACK, items, RuleContext(requirements))
                findings = list(report.findings)
                if not known:
                    known = await retriever.known_mpns()
                for it in items:
                    if it.mpn and _llm_decided(it) and norm_mpn(it.mpn) not in known:
                        findings.append(
                            Finding(
                                rule_id=KB_RULE,
                                severity=Severity.ERROR,
                                message=f"MPN {it.mpn} is not in the knowledge base catalogue",
                                refdes=list(it.refdes),
                                field="mpn",
                                line=it.line,
                                rule_pack=AGENTS_PACK,
                                rule_pack_version=AGENTS_PACK_VERSION,
                            )
                        )
                    if not it.mpn and not it.dnp:
                        findings.append(
                            Finding(
                                rule_id="agents.no_part_selected",
                                severity=Severity.REVIEW,
                                message="no part could be selected from the knowledge base",
                                refdes=list(it.refdes),
                                field="mpn",
                                line=it.line,
                                rule_pack=AGENTS_PACK,
                                rule_pack_version=AGENTS_PACK_VERSION,
                            )
                        )
                error_lines = {f.line for f in findings if f.severity == Severity.ERROR and f.line}
                targets = [
                    i for i, it in enumerate(items) if it.line in error_lines and _llm_decided(it)
                ]
                s.note(f"{len(findings)} findings, {len(targets)} LLM-decided lines to repair")
            return {
                "findings": [f.model_dump(mode="json") for f in findings],
                "repair_targets": targets,
            }

        def after_validate(st: _State) -> str:
            if (
                st.get("repair_targets")
                and st.get("iteration", 0) < config.budget.max_repair_iterations
            ):
                return "repair"
            return "generate"

        async def repair(st: _State) -> _State:
            items = _items(st)
            findings = [Finding.model_validate(f) for f in st.get("findings", [])]
            targets = st.get("repair_targets", [])
            with state.step("repair", "llm", "repairer") as s:
                hits_all = await retriever.search_many(
                    [line_query(items[i]) for i in targets], config.kb_top_k
                )
                fixed = 0
                for idx, hits in zip(targets, hits_all, strict=True):
                    item = items[idx]
                    line_findings = [
                        {
                            "rule": f.rule_id,
                            "severity": f.severity.value,
                            "field": f.field,
                            "message": f.message,
                        }
                        for f in findings
                        if f.line == item.line
                    ]
                    res = await llm.structured(
                        REPAIR,
                        "repairer",
                        RepairResult,
                        line=line_payload(item),
                        findings=line_findings,
                        excerpts=excerpts_block([(h.chunk_id, h.title, h.content) for h in hits]),
                    )
                    if res.give_up or not res.mpn:
                        continue
                    cited = [h.citation() for h in hits if h.chunk_id in set(res.cited_chunks)]
                    prov = llm.provenance("repairer", REPAIR, cited[:3], res.rationale)
                    provenance = dict(item.provenance) | {"mpn": prov}
                    update: dict[str, Any] = {"mpn": res.mpn, "provenance": provenance}
                    if res.manufacturer:
                        update["manufacturer"] = res.manufacturer
                        provenance["manufacturer"] = prov
                    items[idx] = item.model_copy(update=update)
                    fixed += 1
                s.note(
                    f"repaired {fixed}/{len(targets)} lines"
                    f" (iteration {st.get('iteration', 0) + 1})"
                )
            return {"items": _dump(items), "iteration": st.get("iteration", 0) + 1}

        async def generate(st: _State) -> _State:
            with state.step("generate", "rule", "generator") as s:
                items = renumber(_items(st))
                s.note(f"{len(items)} lines")
            return {"items": _dump(items)}

        # LangGraph's overloads do not model closures returning partial TypedDicts
        builder: Any = StateGraph(_State)
        builder.add_node("group", group)
        builder.add_node("select", select)
        builder.add_node("validate", validate)
        builder.add_node("repair", repair)
        builder.add_node("generate", generate)
        builder.add_edge(START, "group")
        builder.add_edge("group", "select")
        builder.add_edge("select", "validate")
        builder.add_conditional_edges(
            "validate", after_validate, {"repair": "repair", "generate": "generate"}
        )
        builder.add_edge("repair", "validate")
        builder.add_edge("generate", END)
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

        items = [BomItem.model_validate(i) for i in final["items"]]
        # final findings refer to pre-renumbering line numbers: re-run deterministic checks
        report = run_pack(DEFAULT_PACK, items, RuleContext(requirements))
        by_ref = {r: it for it in items for r in it.refdes}
        extra = []
        for f in (Finding.model_validate(x) for x in final.get("findings", [])):
            if f.rule_pack == AGENTS_PACK and f.refdes and f.refdes[0] in by_ref:
                still = by_ref[f.refdes[0]]
                if f.rule_id == KB_RULE and norm_mpn(still.mpn) in known:
                    continue
                if f.rule_id == "agents.no_part_selected" and still.mpn:
                    continue
                extra.append(f.model_copy(update={"line": still.line}))
        state.usage = state.usage.model_copy(update={"wall_time_s": round(state.elapsed, 3)})
        bom = BomVersion(
            design_name=design.design_name,
            variant=f"B:{deps.model.id}",
            items=items,
            findings=sorted([*report.findings, *extra], key=lambda f: (f.line or 0, f.rule_id)),
            usage=state.usage,
            kb_snapshot_id=config.kb_snapshot_id,
            rule_pack=DEFAULT_PACK.id,
            rule_pack_version=DEFAULT_PACK.version,
        )
        return RunResult(
            bom=bom,
            trace=state.trace,
            usage=state.usage,
            config=config,
            model=model_info(deps.model),
        )
