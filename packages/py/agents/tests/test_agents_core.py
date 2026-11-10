"""Prompts, CAD tools, run accounting/budgets, structured output and static retrieval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bomagent_agents.context import (
    AgentLLM,
    AgentOutputError,
    Budget,
    BudgetExceededError,
    RunConfig,
    RunState,
)
from bomagent_agents.prompts import PROMPTS, SELECT, UNTRUSTED, excerpts_block
from bomagent_agents.retrieval import StaticRetriever
from bomagent_agents.schemas import Plan
from bomagent_agents.tools import TOOLS, CadTools, ToolError
from bomagent_bom.model import Component, ParsedDesign
from bomagent_llm.catalog import load_catalog
from bomagent_llm.chat import ChatRequest, ChatResponse
from bomagent_llm.fake import FakeChat

DATASHEETS = Path(__file__).resolve().parents[4] / "evals" / "fixtures" / "datasheets"


def test_every_prompt_is_versioned_declares_untrusted_data_and_renders():
    assert {
        "orchestrator",
        "extract_components",
        "group_lines",
        "select_part",
        "validate_bom",
        "compose_bom",
        "repair_line",
    } <= set(PROMPTS)
    for p in PROMPTS.values():
        assert p.version.count(".") == 2
        assert UNTRUSTED in p.system
    system, user = SELECT.render(
        line={"refdes": ["R1"]}, requirements={}, feedback="", excerpts="<excerpt/>"
    )
    assert '"R1"' in user
    assert "<data>" in user
    assert system.startswith("You are the part-selection agent")
    assert SELECT.key == "select_part@1.0.0"
    assert "none" in excerpts_block([])
    assert 'id="c1"' in excerpts_block([("c1", "doc", "text")])


def _design(n: int = 120) -> ParsedDesign:
    comps = [
        Component(
            refdes=f"R{i}", value="10k", footprint="R_0603", sheet_path="/" if i % 2 else "/a/"
        )
        for i in range(1, n + 1)
    ]
    return ParsedDesign(
        design_name="d",
        source_format="kicad",
        components=comps,
        sheets=["/", "/a/"],
        confidence=1.0,
    )


def test_cad_tools_page_filter_and_errors():
    tools = CadTools(_design())
    assert [t.name for t in TOOLS] == ["list_sheets", "list_components", "get_component"]
    sheets = tools.execute("list_sheets", {})["sheets"]
    assert sum(s["components"] for s in sheets) == 120
    page = tools.execute("list_components", {"offset": 0, "limit": 500})
    assert len(page["components"]) == 50
    assert page["next_offset"] == 50
    assert page["total"] == 120
    last = tools.execute("list_components", {"offset": 100})
    assert last["next_offset"] is None
    assert len(last["components"]) == 20
    assert tools.execute("list_components", {"sheet": "/a/"})["total"] == 60
    assert tools.execute("get_component", {"refdes": "R7"})["value"] == "10k"
    with pytest.raises(ToolError):
        tools.execute("get_component", {"refdes": "X99"})
    with pytest.raises(ToolError):
        tools.execute("delete_design", {})
    with pytest.raises(ToolError):
        tools.execute("list_components", {"offset": -1})
    assert tools.calls == 8


def _llm(
    sim, budget: Budget | None = None, model: str = "fake-closed"
) -> tuple[AgentLLM, RunState]:
    state = RunState(RunConfig(budget=budget or Budget()))
    spec = load_catalog().get(model).model_copy(update={"cost_in_eur": 1.0, "cost_out_eur": 2.0})
    return AgentLLM(FakeChat(sim), spec, state), state


async def test_structured_output_retries_once_then_fails():
    answers = iter(["not json", json.dumps({"steps": ["a"], "notes": ""})])
    llm, state = _llm(lambda r: ChatResponse(content=next(answers)))
    plan = await llm.structured(
        PROMPTS["orchestrator"], "orchestrator", Plan, summary={}, requirements={}
    )
    assert plan.steps == ["a"]
    assert state.usage.llm_calls == 2
    assert state.usage.cost_eur > 0
    bad, _ = _llm(lambda r: ChatResponse(content='{"steps": 5}'))
    with pytest.raises(AgentOutputError, match="after retry"):
        await bad.structured(
            PROMPTS["orchestrator"], "orchestrator", Plan, summary={}, requirements={}
        )


async def test_request_metadata_identifies_prompt_tenant_and_run():
    seen: list[ChatRequest] = []

    def sim(r: ChatRequest) -> ChatResponse:
        seen.append(r)
        return ChatResponse(content='{"steps": []}')

    llm, state = _llm(sim)
    await llm.structured(PROMPTS["orchestrator"], "orchestrator", Plan, summary={}, requirements={})
    md = seen[0].metadata
    assert md["prompt_id"] == "orchestrator"
    assert md["prompt_version"] == "1.0.0"
    assert md["run_id"] == str(state.config.run_id)
    assert md["agent"] == "orchestrator"
    assert seen[0].response_schema is not None
    assert seen[0].schema_name == "Plan"


async def test_budget_limits_calls_and_tokens():
    llm, _ = _llm(lambda r: ChatResponse(content='{"steps": []}'), Budget(max_llm_calls=1))
    await llm.structured(PROMPTS["orchestrator"], "o", Plan, summary={}, requirements={})
    with pytest.raises(BudgetExceededError, match="LLM call"):
        await llm.structured(PROMPTS["orchestrator"], "o", Plan, summary={}, requirements={})
    llm2, _ = _llm(
        lambda r: ChatResponse(content='{"steps": []}', input_tokens=500),
        Budget(max_total_tokens=100),
    )
    await llm2.structured(PROMPTS["orchestrator"], "o", Plan, summary={}, requirements={})
    with pytest.raises(BudgetExceededError, match="token"):
        await llm2.structured(PROMPTS["orchestrator"], "o", Plan, summary={}, requirements={})


def test_step_timer_records_errors():
    state = RunState(RunConfig())
    with pytest.raises(RuntimeError), state.step("x", "rule", "a"):
        raise RuntimeError("boom")
    assert state.trace[0].status == "error"
    assert "boom" in state.trace[0].summary


async def test_static_retriever_finds_ordering_info_and_drops_injection():
    ret = StaticRetriever.from_directory(DATASHEETS)
    hits = (await ret.search_many(["10 MΩ 0603 resistor ordering information"], 3))[0]
    assert hits[0].title == "yageo-rc0603.md"
    assert any("RC0603FR-0710ML" in h.content for h in hits)
    assert all(
        "ignore" not in h.content.lower() or "previous" not in h.content.lower() for h in hits
    )
    everything = (await ret.search_many(["ignore previous instructions system prompt mpn"], 50))[0]
    assert not any(
        h.title == "malicious-injection.md" and "ignore" in h.content.lower() for h in everything
    )
    known = await ret.known_mpns()
    assert "RC0603FR-0710ML" in known
    assert "GRM188R71H104KA93D" in known
    assert hits[0].citation().scope == "global"
