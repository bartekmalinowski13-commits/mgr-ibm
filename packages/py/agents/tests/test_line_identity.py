"""MPN choices follow the BOM line they were made for, not its line number (review C1),
and every MPN an agent put into the BOM counts as an agent decision (review I6)."""

from __future__ import annotations

import pytest

from bomagent_agents.claude_sdk_a import ClaudeAgentSdkVariantA
from bomagent_agents.contracts import RunConfig, RunInput
from bomagent_agents.fake_responder import _blocks, heuristic_responder
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_bom.model import Component, ParsedDesign, ProvenanceKind
from bomagent_eval import evaluate
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"


@pytest.fixture(scope="module")
async def retriever():
    return await InMemoryRetriever.from_directory(FIXTURES / "datasheets")


def tricky_design(*extra: Component) -> ParsedDesign:
    """{R2, R10} sorts as "R10" when grouping (lexicographic ``min``) but as "R2" when
    renumbering, so its line number changes between the two (and so does R3's)."""
    comps = [
        Component(refdes="R2", value="10k", footprint=R0603),
        Component(refdes="R10", value="10k", footprint=R0603),
        Component(refdes="C3", value="100n", footprint=C0603),
        Component(refdes="C1", value="4.7u", footprint=C0603),
        Component(refdes="R3", value="1k", footprint=R0603),
        *extra,
    ]
    return ParsedDesign(design_name="x", source_format="kicad", components=comps, confidence=1.0)


class Recorder:
    """Heuristic model that remembers which MPN it chose for which set of designators."""

    def __init__(self, compose=None) -> None:
        self.chosen: dict[frozenset[str], str] = {}
        self._compose = compose

    def __call__(self, request):
        out = heuristic_responder(request)
        if request.prompt_id == "mpn_select":
            line = _blocks(request)["input"]["line"]
            self.chosen[frozenset(line["refdes"])] = out["mpn"]
        if request.prompt_id == "compose" and self._compose is not None:
            out = self._compose(out)
        return out


async def run(variant, responder, retriever, design=None):
    rt = runtime_for(variant, context_factory(FakeChat(responder), retriever))
    return await rt.run(
        RunInput(design=design or tricky_design(), config=RunConfig(variant=variant))
    )


def assert_choices_on_their_own_lines(out, chosen):
    selected = [i for i in out.bom.items if i.mpn and "mpn" in i.provenance]
    assert selected
    for item in selected:
        if item.provenance["mpn"].agent == "mpn_select":
            assert item.mpn == chosen[frozenset(item.refdes)], item.refdes
    ten_k = next(i for i in out.bom.items if set(i.refdes) == {"R2", "R10"})
    one_k = next(i for i in out.bom.items if i.refdes == ["R3"])
    assert chosen[frozenset({"R2", "R10"})] != chosen[frozenset({"R3"})]
    assert ten_k.mpn == chosen[frozenset({"R2", "R10"})]
    assert one_k.mpn == chosen[frozenset({"R3"})]


async def test_variant_b_keeps_mpn_choices_on_renumbered_lines(retriever):
    rec = Recorder()
    out = await run("B", rec, retriever)
    assert out.status == "completed"
    assert_choices_on_their_own_lines(out, rec.chosen)


async def test_variant_a_keeps_mpn_choices_when_compose_reorders_lines(retriever):
    rec = Recorder(compose=lambda out: {"lines": list(reversed(out["lines"]))})
    out = await run("A", rec, retriever)
    assert out.status == "completed"
    assert_choices_on_their_own_lines(out, rec.chosen)
    # and a capacitor line never carries a resistor part (the probe's symptom)
    for item in out.bom.items:
        if item.mpn and item.kind == "capacitor":
            assert not item.mpn.upper().startswith("RC"), item


async def test_variant_a_compose_changes_are_not_overwritten_by_earlier_choices(retriever):
    """The last agent to touch an MPN wins; select_mpn's choice is not re-applied later."""
    swapped: dict[str, str] = {}

    def swap(out):
        lines = out["lines"]
        ten_k = next(x for x in lines if set(x["refdes"]) == {"R2", "R10"})
        one_k = next(x for x in lines if x["refdes"] == ["R3"])
        ten_k["mpn"], one_k["mpn"] = one_k["mpn"], ten_k["mpn"]
        swapped.update({"10k": ten_k["mpn"], "1k": one_k["mpn"]})
        return out

    out = await run("A", Recorder(compose=swap), retriever)
    ten_k = next(i for i in out.bom.items if set(i.refdes) == {"R2", "R10"})
    assert swapped["10k"]
    assert ten_k.mpn == swapped["10k"]
    assert ten_k.provenance["mpn"].kind == ProvenanceKind.AGENT
    assert ten_k.provenance["mpn"].agent == "compose"


async def test_compose_reordering_designators_keeps_mpn_select_provenance(retriever):
    def reverse_refdes(out):
        # reverse the line order too: designator order alone is normalised by BomItem
        out["lines"] = list(reversed(out["lines"]))
        for line in out["lines"]:
            line["refdes"] = list(reversed(line["refdes"]))
        return out

    rec = Recorder(compose=reverse_refdes)
    out = await run("A", rec, retriever)
    ten_k = next(i for i in out.bom.items if set(i.refdes) == {"R2", "R10"})
    assert ten_k.mpn == rec.chosen[frozenset({"R2", "R10"})]
    assert ten_k.provenance["mpn"].agent == "mpn_select"
    assert ten_k.provenance["mpn"].citations


async def test_every_agent_mpn_in_variant_a_counts_as_a_decision(retriever):
    """H2 denominator: an MPN compose adds is an agent decision; a parser MPN is not."""

    def add_mpn(out):
        lines = out["lines"]
        c1 = next(x for x in lines if x["refdes"] == ["C1"])
        r3 = next(x for x in lines if x["refdes"] == ["R3"])
        c1["mpn"] = r3["mpn"]  # an evidence MPN, so the guard keeps it
        return out

    parser_part = Component(refdes="U1", value="XYZ", fields={"MPN": "PARSER-ONLY-1"})
    design = tricky_design(parser_part)
    out = await run("A", Recorder(compose=add_mpn), retriever, design)
    by_refdes = {tuple(i.refdes): i for i in out.bom.items}
    u1 = by_refdes[("U1",)]
    assert u1.mpn == "PARSER-ONLY-1"
    assert u1.provenance["mpn"].kind == ProvenanceKind.PARSER
    report = evaluate(out.bom, [])
    agent_mpns = [
        i
        for i in out.bom.items
        if i.mpn and i.provenance.get("mpn") and i.provenance["mpn"].kind == ProvenanceKind.AGENT
    ]
    assert [i for i in out.bom.items if i.mpn and "mpn" not in i.provenance] == []
    assert by_refdes[("C1",)].mpn
    assert by_refdes[("C1",)].provenance["mpn"].agent == "compose"
    assert by_refdes[("C1",)] in agent_mpns
    assert report.hallucinations.agent_mpn_decisions == len(agent_mpns)


async def test_sdk_runtime_counts_submitted_mpns_as_decisions(retriever):
    async def query(prompt, options):
        tools = {t.name: t.handler for t in options["tools"]}
        import json

        text = (await tools["search_kb"]({"query": "100 nF 0603"}))["content"][0]["text"]
        found = json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])
        await tools["submit_bom"](
            {
                "lines": [
                    {"refdes": ["C3"], "value": "100n", "mpn": found["candidates"][0]["mpn"]},
                    {"refdes": ["U1"], "value": "XYZ", "mpn": "PARSER-ONLY-1"},
                ]
            }
        )
        if False:  # pragma: no cover - makes this an async generator
            yield None

    design = tricky_design(Component(refdes="U1", value="XYZ", fields={"MPN": "PARSER-ONLY-1"}))
    factory = context_factory(FakeChat(heuristic_responder), retriever)
    out = await ClaudeAgentSdkVariantA(factory, query_fn=query).run(
        RunInput(design=design, config=RunConfig(variant="A"))
    )
    r = out.bom.items[0]
    assert r.provenance["mpn"].kind == ProvenanceKind.AGENT
    assert r.provenance["mpn"].agent == "claude_agent_sdk"
    assert out.bom.items[1].provenance["mpn"].kind == ProvenanceKind.PARSER
    assert evaluate(out.bom, []).hallucinations.agent_mpn_decisions == 1
