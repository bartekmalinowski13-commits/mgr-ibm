"""Variants A and B end-to-end on the KiCad fixtures with the fake provider."""

from __future__ import annotations

import pytest

from bomagent_agents.contracts import RunConfig, RunInput
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_bom.model import ProvenanceKind
from bomagent_cad import FileRef, parse_files
from bomagent_eval import evaluate, load_reference
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES, kicad_project_paths


@pytest.fixture(scope="module")
async def retriever():
    return await InMemoryRetriever.from_directory(FIXTURES / "datasheets")


def design(project: str):
    return parse_files([FileRef.from_path(p) for p in kicad_project_paths(project)])


async def run_variant(variant, project, retriever, **cfg):
    chat = FakeChat(heuristic_responder)
    runtime = runtime_for(variant, context_factory(chat, retriever))
    out = await runtime.run(
        RunInput(design=design(project), config=RunConfig(variant=variant, **cfg))
    )
    return out, chat


@pytest.mark.parametrize("variant", ["A", "B"])
@pytest.mark.parametrize("project", ["ecg-frontend", "eeg-2ch"])
async def test_variant_produces_bom_close_to_reference(variant, project, retriever):
    out, chat = await run_variant(variant, project, retriever)
    assert out.status == "completed"
    assert out.bom.items
    ref = load_reference(KICAD_FIXTURES / project / "reference_bom.csv")
    report = evaluate(out.bom, ref, known_mpns=await retriever.known_mpns())
    assert report.designators.f1 == 1.0
    assert report.hallucinations.unverified == 0
    # missing MPNs were completed from the KB (fake provider; real models in M8)
    assert report.hallucinations.coverage >= (0.9 if variant == "B" else 0.7)
    assert out.usage.llm_calls == len(chat.calls) > 0
    assert out.trace[0].node in {"normalize_group", "extract_group"}


async def test_variant_b_calls_llm_only_for_unresolved_lines(retriever):
    out_b, chat_b = await run_variant("B", "ecg-frontend", retriever)
    out_a, chat_a = await run_variant("A", "ecg-frontend", retriever)
    assert {c.prompt_id for c in chat_b.calls} == {"mpn_select"}
    assert {c.prompt_id for c in chat_a.calls} >= {
        "extract_group",
        "mpn_select",
        "validate",
        "compose",
    }
    assert out_b.usage.llm_calls < out_a.usage.llm_calls


async def test_provenance_records_rules_and_agents(retriever):
    out, _ = await run_variant("B", "ecg-frontend", retriever)
    r5 = next(i for i in out.bom.items if "R5" in i.refdes)
    assert r5.provenance["quantity"].kind == ProvenanceKind.RULE
    mpn_prov = r5.provenance["mpn"]
    assert mpn_prov.kind == ProvenanceKind.AGENT
    assert mpn_prov.prompt_id == "mpn_select"
    assert mpn_prov.prompt_version.startswith("1+")
    assert mpn_prov.model_id == "fake-closed"
    assert mpn_prov.citations
    assert out.bom.rule_pack == "core"
    out_a, _ = await run_variant("A", "ecg-frontend", retriever)
    assert out_a.bom.items[0].provenance["quantity"].kind == ProvenanceKind.AGENT


async def test_budget_stops_the_run(retriever):
    out, _ = await run_variant("B", "ecg-frontend", retriever, max_llm_calls=2)
    assert out.status == "budget_exceeded"
    assert any(f.rule_id == "run.budget" for f in out.bom.findings)


async def test_invented_mpn_is_rejected(retriever):
    def liar(request):
        if request.prompt_id == "mpn_select":
            return {"mpn": "INVENTED-123", "manufacturer": "Nobody", "confidence": 1.0}
        return heuristic_responder(request)

    runtime = runtime_for("B", context_factory(FakeChat(liar), retriever))
    out = await runtime.run(RunInput(design=design("ecg-frontend"), config=RunConfig(variant="B")))
    assert all(i.mpn != "INVENTED-123" for i in out.bom.items)


async def test_open_weight_model_and_unknown_runtime(retriever):
    _, chat = await run_variant("B", "pulse-ox", retriever, model_id="fake-open-weight")
    assert chat.calls[0].model.license_class.value == "open-weight"
    with pytest.raises(ValueError, match="unknown runtime"):
        runtime_for("A", context_factory(chat, retriever), runtime="nope")


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_every_finished_step_is_reported_as_it_happens(variant, retriever):
    """Live progress (SSE): the callback sees each step once, with the usage so far."""
    seen = []

    async def on_step(step, usage):
        seen.append((step.node, usage.llm_calls))

    factory = context_factory(FakeChat(heuristic_responder), retriever, on_step=on_step)
    result = await runtime_for(variant, factory).run(
        RunInput(
            design=design("pulse-ox"), config=RunConfig(variant=variant, model_id="fake-closed")
        )
    )
    assert [node for node, _ in seen] == [s.node for s in result.trace]
    calls = [c for _, c in seen]
    assert calls == sorted(calls)  # usage only grows
    assert calls[-1] <= result.usage.llm_calls


async def test_a_failing_progress_callback_does_not_break_the_run(retriever):
    async def broken(step, usage):
        raise RuntimeError("database unavailable")

    factory = context_factory(FakeChat(heuristic_responder), retriever, on_step=broken)
    result = await runtime_for("B", factory).run(
        RunInput(design=design("pulse-ox"), config=RunConfig(variant="B", model_id="fake-closed"))
    )
    assert result.status == "completed"
