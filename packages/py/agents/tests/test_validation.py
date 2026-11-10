"""Validation stage alone (thesis metric "skuteczność walidacji" on injected errors)."""

from __future__ import annotations

import pytest

from bomagent_agents.contracts import RunConfig
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_agents.validation import validate_bom, validation_context
from bomagent_bom.model import Requirements
from bomagent_eval.injection import detection_report, inject_errors
from bomagent_eval.reference import load_reference
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, KICAD_FIXTURES


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_each_variant_validator_detects_a_removed_footprint(variant):
    reference = load_reference(KICAD_FIXTURES / "ecg-frontend" / "reference_bom.csv")
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    ctx = validation_context(
        FakeChat(heuristic_responder),
        retriever,
        RunConfig(variant=variant, model_id="fake-closed"),
        Requirements(),
    )
    baseline = await validate_bom(variant, ctx, reference)
    mutated, errors = inject_errors(reference, n=1, seed=3, kinds=("drop_footprint",))
    findings = await validate_bom(variant, ctx, mutated)
    report = detection_report(errors, findings, baseline)
    assert report.injected == 1
    assert report.detected == 1
    if variant == "A":
        assert ctx.budget.usage.llm_calls > 0  # the LLM validated
    else:
        assert ctx.budget.usage.llm_calls == 0  # deterministic rules only


async def test_unknown_variant_is_rejected():
    retriever = await InMemoryRetriever.from_directory(FIXTURES / "datasheets")
    ctx = validation_context(
        FakeChat(heuristic_responder),
        retriever,
        RunConfig(variant="A", model_id="fake-closed"),
        Requirements(),
    )
    with pytest.raises(ValueError, match="variant"):
        await validate_bom("C", ctx, [])
