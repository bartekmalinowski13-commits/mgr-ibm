"""Variants A and B end to end on the KiCad fixtures with the deterministic simulator,
plus the feedback loops, failure handling, provenance and the SDK adapter contract.

Simulated runs test the plumbing; they say nothing about real model quality."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bomagent_agents import Budget, Dependencies, RunConfig, StaticRetriever, get_runtime
from bomagent_agents.runtimes import UnknownVariantError
from bomagent_agents.runtimes.claude_sdk_a import (
    ClaudeSdkVariantA,
    LoopResult,
    ResidencyError,
    build_tools,
    check_bedrock_eu,
)
from bomagent_agents.runtimes.variant_b import KB_RULE
from bomagent_agents.simulators import simulate
from bomagent_bom.model import ProvenanceKind, Requirements, Usage
from bomagent_cad import FileRef, parse_files
from bomagent_eval import evaluate, load_reference
from bomagent_llm.catalog import load_catalog
from bomagent_llm.chat import ChatRequest, ChatResponse
from bomagent_llm.fake import FakeChat

ROOT = Path(__file__).resolve().parents[4] / "evals" / "fixtures"
PROJECTS = ["ecg-frontend", "eeg-2ch", "pulse-ox"]
RETRIEVER = StaticRetriever.from_directory(ROOT / "datasheets")


def _design(project: str):
    folder = ROOT / "kicad" / project
    files = [
        FileRef.from_path(p)
        for p in sorted(folder.iterdir())
        if p.suffix in {".kicad_sch", ".kicad_pro"}
    ]
    return parse_files(files)


def _deps(sim=simulate, model: str = "fake-closed") -> Dependencies:
    return Dependencies(chat=FakeChat(sim), model=load_catalog().get(model), retriever=RETRIEVER)


async def _run(
    variant: str,
    project: str,
    sim=simulate,
    budget: Budget | None = None,
    model: str = "fake-closed",
):
    cfg = RunConfig(variant=variant, model_id=model, budget=budget or Budget())
    return await get_runtime(variant).run(_design(project), Requirements(), cfg, _deps(sim, model))


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("variant", ["A", "B"])
async def test_variants_produce_reference_quality_boms_with_simulator(variant, project):
    result = await _run(variant, project)
    assert result.status == "completed", result.error
    known = await RETRIEVER.known_mpns()
    ref = load_reference(ROOT / "kicad" / project / "reference_bom.csv")
    s = evaluate(result.bom, ref, known_mpns=known).summary()
    assert s["designator_f1"] == 1.0
    assert s["line_f1"] >= 0.95
    assert s["mpn_hallucination_rate"] == 0.0
    assert result.usage.llm_calls >= 1
    assert result.usage.input_tokens > 0
    assert result.bom.variant.startswith(f"{variant}:fake-closed")
    assert [t.status for t in result.trace] == ["ok"] * len(result.trace)
    assert result.model["license_class"] == "closed"


async def test_variant_b_is_cheaper_than_a_and_uses_rules_for_grouping():
    a = await _run("A", "ecg-frontend")
    b = await _run("B", "ecg-frontend")
    assert b.usage.llm_calls < a.usage.llm_calls
    assert [t.kind for t in b.trace if t.step in {"group", "validate", "generate"}] == ["rule"] * 3
    assert {t.kind for t in a.trace} == {"llm"}
    line = next(i for i in b.bom.items if "R1" in i.refdes)
    assert line.provenance["quantity"].kind == ProvenanceKind.RULE
    assert line.provenance["mpn"].kind == ProvenanceKind.AGENT
    assert line.provenance["mpn"].citations
    assert line.provenance["mpn"].prompt_id == "select_part"
    a_line = next(i for i in a.bom.items if "R1" in i.refdes)
    assert a_line.provenance["quantity"].kind == ProvenanceKind.AGENT


async def test_open_weight_model_runs_through_the_same_contract():
    result = await _run("B", "pulse-ox", model="fake-open-weight")
    assert result.status == "completed"
    assert result.model["license_class"] == "open-weight"


def _hallucinating_once():
    state = {"done": False}

    def sim(req: ChatRequest) -> ChatResponse:
        if (
            req.metadata.get("prompt_id") == "select_part"
            and not state["done"]
            and '"R1"' in (req.messages[-1].content or "")
        ):
            state["done"] = True
            return ChatResponse(
                content=json.dumps(
                    {"mpn": "RC0603FR-07INVENTED", "manufacturer": "Yageo", "confidence": 0.9}
                )
            )
        return simulate(req)

    return sim


async def test_variant_b_repairs_a_hallucinated_part_rejected_by_the_kb_rule():
    result = await _run("B", "ecg-frontend", _hallucinating_once())
    assert result.status == "completed"
    steps = [t.step for t in result.trace]
    assert steps == ["group", "select", "validate", "repair", "validate", "generate"]
    line = next(i for i in result.bom.items if "R1" in i.refdes)
    assert line.mpn == "RC0603FR-0710ML"
    assert line.provenance["mpn"].prompt_id == "repair_line"
    assert not [f for f in result.bom.findings if f.rule_id == KB_RULE]


async def test_variant_b_reports_unrepairable_line_after_max_iterations():
    def sim(req: ChatRequest) -> ChatResponse:
        pid = req.metadata.get("prompt_id")
        if pid == "select_part" and '"R1"' in (req.messages[-1].content or ""):
            return ChatResponse(content=json.dumps({"mpn": "NOPE-0000X1", "confidence": 0.5}))
        if pid == "repair_line":
            return ChatResponse(content=json.dumps({"give_up": True}))
        return simulate(req)

    result = await _run("B", "ecg-frontend", sim, Budget(max_repair_iterations=1))
    assert [t.step for t in result.trace].count("repair") == 1
    kb = [f for f in result.bom.findings if f.rule_id == KB_RULE]
    assert kb
    assert kb[0].refdes[0] == "R1"


async def test_variant_a_reselects_lines_flagged_by_its_validator():
    calls = {"validate": 0}

    def sim(req: ChatRequest) -> ChatResponse:
        if req.metadata.get("prompt_id") == "validate_bom":
            calls["validate"] += 1
            if calls["validate"] == 1:
                return ChatResponse(
                    content=json.dumps(
                        {
                            "issues": [
                                {
                                    "refdes": ["R7"],
                                    "field": "mpn",
                                    "severity": "error",
                                    "message": "wrong tolerance",
                                    "reselect": True,
                                }
                            ]
                        }
                    )
                )
        return simulate(req)

    result = await _run("A", "ecg-frontend", sim)
    steps = [t.step for t in result.trace]
    assert steps == [
        "plan",
        "extract",
        "group",
        "select",
        "validate",
        "select",
        "validate",
        "compose",
    ]
    assert result.status == "completed"


async def test_variant_a_keeps_schema_violations_visible():
    def sim(req: ChatRequest) -> ChatResponse:
        if req.metadata.get("prompt_id") == "compose_bom":
            lines = json.loads(simulate(req).content)["lines"]
            lines[0]["refdes"] = lines[0]["refdes"] + lines[0]["refdes"][:1]
            return ChatResponse(content=json.dumps({"lines": lines}))
        return simulate(req)

    result = await _run("A", "pulse-ox", sim)
    assert any(f.rule_id == "schema.coerced" for f in result.bom.findings)


async def test_budget_exhaustion_fails_the_run_with_a_trace():
    result = await _run("A", "ecg-frontend", budget=Budget(max_llm_calls=3))
    assert result.status == "failed"
    assert "BudgetExceeded" in (result.error or "")
    assert result.bom is None
    assert result.trace
    assert result.trace[-1].status == "error"


async def test_invalid_model_output_fails_the_run():
    def sim(req: ChatRequest) -> ChatResponse:
        if req.metadata.get("prompt_id") == "group_lines":
            return ChatResponse(content="I think the BOM is fine")
        return simulate(req)

    result = await _run("A", "pulse-ox", sim)
    assert result.status == "failed"
    assert "AgentOutputError" in (result.error or "")


async def test_extractor_reads_all_pages_of_a_large_design():
    from bomagent_bom.model import Component, ParsedDesign

    comps = [
        Component(refdes=f"R{i}", value="10k", footprint="Resistor_SMD:R_0603_1608Metric")
        for i in range(1, 131)
    ]
    design = ParsedDesign(
        design_name="big", source_format="kicad", components=comps, confidence=1.0
    )
    result = await get_runtime("A").run(design, Requirements(), RunConfig(variant="A"), _deps())
    assert result.status == "completed", result.error
    assert result.bom.items[0].quantity == 130
    assert result.usage.tool_calls == 3


def test_unknown_variant():
    with pytest.raises(UnknownVariantError):
        get_runtime("C")


class _ScriptedLoop:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tools: list[str] = []

    async def run(self, system, user, tools, model):
        self.tools = sorted(tools)
        listing = await tools["list_components"][1]({"offset": 0})
        assert listing["total"] > 0
        assert "error" in await tools["get_component"][1]({"refdes": "NOPE1"})
        assert "excerpts" in await tools["search_kb"][1]({"query": "100 nF 0603"})
        return LoopResult(self.text, Usage(llm_calls=4, input_tokens=1000, output_tokens=200))


async def test_claude_sdk_adapter_contract_with_scripted_loop():
    lines = {
        "lines": [
            {
                "refdes": ["C1", "C2"],
                "quantity": 2,
                "kind": "capacitor",
                "value": "100n",
                "mpn": "GRM188R71H104KA93D",
            }
        ]
    }
    loop = _ScriptedLoop(json.dumps(lines))
    result = await ClaudeSdkVariantA(loop).run(
        _design("pulse-ox"), Requirements(), RunConfig(variant="A-sdk"), _deps()
    )
    assert result.status == "completed"
    assert loop.tools == ["get_component", "list_components", "list_sheets", "search_kb"]
    assert result.bom.items[0].refdes == ["C1", "C2"]
    assert result.usage.input_tokens == 1000
    broken = await ClaudeSdkVariantA(_ScriptedLoop("no json")).run(
        _design("pulse-ox"), Requirements(), RunConfig(), _deps()
    )
    assert broken.status == "failed"


def test_sdk_adapter_requires_bedrock_in_the_eu():
    with pytest.raises(ResidencyError):
        check_bedrock_eu({})
    with pytest.raises(ResidencyError):
        check_bedrock_eu({"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"})
    check_bedrock_eu({"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "eu-central-1"})
    assert "search_kb" in build_tools(_design("pulse-ox"), RETRIEVER, 3)
