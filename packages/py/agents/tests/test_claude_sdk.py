"""Claude Agent SDK adapter with a scripted stand-in for the SDK's query loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from bomagent_agents.claude_sdk_a import ClaudeAgentSdkVariantA
from bomagent_agents.contracts import RunConfig, RunInput
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_cad import FileRef, parse_files
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, kicad_project_paths


@dataclass
class ResultMessage:
    num_turns: int = 3
    usage: dict = field(default_factory=lambda: {"input_tokens": 1000, "output_tokens": 200})


def scripted_query(submit: bool = True):
    async def query(prompt, options):
        tools = {t.name: t.handler for t in options["tools"]}
        comps = await tools["get_components"]({})
        assert '<data name="components">' in comps["content"][0]["text"]
        text = (await tools["search_kb"]({"query": "100 nF 0603"}))["content"][0]["text"]
        assert text.startswith('<data name="knowledge">')
        found = json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])
        assert found["candidates"]
        if submit:
            await tools["submit_bom"](
                {
                    "lines": [
                        {
                            "refdes": ["C1", "C2"],
                            "quantity": 2,
                            "value": "100n",
                            "footprint": "Capacitor_SMD:C_0603_1608Metric",
                            "mpn": found["candidates"][0]["mpn"],
                        }
                    ]
                }
            )
        yield ResultMessage()

    return query


@pytest.fixture(scope="module")
async def retriever():
    return await InMemoryRetriever.from_directory(FIXTURES / "datasheets")


def run_input():
    design = parse_files([FileRef.from_path(p) for p in kicad_project_paths("pulse-ox")])
    return RunInput(design=design, config=RunConfig(variant="A"))


async def test_adapter_collects_submitted_bom_and_usage(retriever):
    factory = context_factory(FakeChat(heuristic_responder), retriever)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=scripted_query()).run(run_input())
    assert out.status == "completed"
    assert out.runtime == "claude_agent_sdk_a"
    assert out.bom.items[0].refdes == ["C1", "C2"]
    assert out.usage.input_tokens == 1000
    assert out.usage.llm_calls == 3


async def test_adapter_without_submission_fails_cleanly(retriever):
    factory = context_factory(FakeChat(heuristic_responder), retriever)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=scripted_query(False)).run(run_input())
    assert out.status == "failed"
    assert out.bom.findings[0].rule_id == "run.no_result"


def test_registry_builds_sdk_runtime(retriever):
    runtime = runtime_for(
        "A", context_factory(FakeChat(heuristic_responder), retriever), runtime="claude_agent_sdk_a"
    )
    assert runtime.name == "claude_agent_sdk_a"


async def test_adapter_pins_the_kb_snapshot_and_caps_turns_by_the_budget(retriever):
    seen: dict = {}

    async def query(prompt, options):
        seen.update(options)
        async for m in scripted_query()(prompt, options):
            yield m

    factory = context_factory(FakeChat(heuristic_responder), retriever)
    run = run_input()
    run.config = RunConfig(variant="A", kb_snapshot_id="snap-7", max_llm_calls=12)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=query).run(run)
    assert out.bom.kb_snapshot_id == "snap-7"
    assert seen["max_turns"] == 12  # min(adapter default 40, run budget)


async def test_adapter_stops_at_the_time_budget(retriever):
    import asyncio

    async def slow(prompt, options):
        await asyncio.sleep(5)
        yield ResultMessage()

    factory = context_factory(FakeChat(heuristic_responder), retriever)
    run = run_input()
    run.config = RunConfig(variant="A", timeout_s=0.05)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=slow).run(run)
    assert out.status == "budget_exceeded"
    assert any(f.rule_id == "run.budget" for f in out.bom.findings)


async def test_adapter_flags_a_run_over_the_token_budget(retriever):
    factory = context_factory(FakeChat(heuristic_responder), retriever)
    run = run_input()
    run.config = RunConfig(variant="A", max_total_tokens=500)  # scripted run uses 1200
    out = await ClaudeAgentSdkVariantA(factory, query_fn=scripted_query()).run(run)
    assert out.status == "budget_exceeded"
    assert any(f.rule_id == "run.budget" for f in out.bom.findings)
    assert out.bom.items  # the submitted BOM is kept for inspection


async def test_a_timed_out_run_keeps_the_usage_of_the_turns_it_made(retriever):
    import asyncio

    @dataclass
    class AssistantMessage:
        usage: dict = field(default_factory=lambda: {"input_tokens": 700, "output_tokens": 50})

    async def two_turns_then_hang(prompt, options):
        yield AssistantMessage()
        yield AssistantMessage()
        await asyncio.sleep(5)
        yield ResultMessage()

    factory = context_factory(FakeChat(heuristic_responder), retriever)
    run = run_input()
    run.config = RunConfig(variant="A", timeout_s=0.1)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=two_turns_then_hang).run(run)
    assert out.status == "budget_exceeded"
    assert out.usage.llm_calls == 2  # metered even though no final result arrived
    assert out.usage.input_tokens == 1400
    assert out.usage.output_tokens == 100
