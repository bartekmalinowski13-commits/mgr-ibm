"""Resume of a crashed run from its last checkpoint (ARCH-05), both variants."""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from bomagent_agents.contracts import RunConfig, RunInput
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.registry import context_factory, runtime_for
from bomagent_agents.resume import RESUME_NODE, InMemoryStateStore
from bomagent_agents.retrieval import InMemoryRetriever
from bomagent_cad import FileRef, parse_files
from bomagent_llm.chat import FakeChat
from bomagent_testing.data import FIXTURES, kicad_project_paths


class WorkerCrashError(Exception):
    """Stands in for a lost worker: raised out of the graph, nothing is cleaned up."""


class CrashingChat(FakeChat):
    def __init__(self, crash_after: int) -> None:
        super().__init__(heuristic_responder)
        self.crash_after = crash_after

    async def complete(self, request):  # type: ignore[no-untyped-def]
        if len(self.calls) >= self.crash_after:
            raise WorkerCrashError
        return await super().complete(request)


@pytest.fixture(scope="module")
async def retriever():
    return await InMemoryRetriever.from_directory(FIXTURES / "datasheets")


def _run(variant: str) -> RunInput:
    design = parse_files([FileRef.from_path(p) for p in kicad_project_paths("pulse-ox")])
    return RunInput(run_id=uuid.uuid4(), design=design, config=RunConfig(variant=variant))


def _lines(out):  # type: ignore[no-untyped-def]
    """The BOM without provenance timestamps (they differ between any two runs)."""
    return [i.model_dump(mode="json", exclude={"provenance"}) for i in out.bom.items], [
        f.model_dump(mode="json") for f in out.bom.findings
    ]


def _factory(chat, retriever, saver, store, **kw):  # type: ignore[no-untyped-def]
    return context_factory(
        chat, retriever, checkpointer=lambda _r: saver, state_store=lambda _r: store, **kw
    )


@pytest.mark.parametrize(("variant", "crash_after"), [("A", 5), ("B", 0)])
async def test_crashed_run_resumes_from_its_last_checkpoint(retriever, variant, crash_after):
    run = _run(variant)
    reference = await runtime_for(
        variant, context_factory(FakeChat(heuristic_responder), retriever)
    ).run(run)

    saver, store = InMemorySaver(), InMemoryStateStore()
    with pytest.raises(WorkerCrashError):
        await runtime_for(
            variant, _factory(CrashingChat(crash_after=crash_after), retriever, saver, store)
        ).run(run)

    chat = FakeChat(heuristic_responder)
    steps_before = len(store.states[run.run_id]["trace"])
    resumed = await runtime_for(
        variant, _factory(chat, retriever, saver, store, resume=True, resume_attempt=2)
    ).run(run)

    # same BOM as an uninterrupted run, and less LLM work than a restart would take
    assert resumed.status == reference.status == "completed"
    assert _lines(resumed) == _lines(reference)
    assert len(chat.calls) <= reference.usage.llm_calls - (1 if variant == "A" else 0)
    # the resume is on record: which checkpoint, how much was restored, which attempt
    record = resumed.resumed
    assert record is not None
    assert record.mode == "checkpoint"
    assert record.checkpoint_id
    assert record.attempt == 2
    assert record.restored_steps == steps_before
    markers = [s for s in resumed.trace if s.node == RESUME_NODE]
    assert len(markers) == 1
    assert markers[0].detail["checkpoint_id"] == record.checkpoint_id
    # spend of the interrupted part stays in the budget
    assert resumed.usage.llm_calls >= record.restored_llm_calls + len(chat.calls)


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_resume_without_a_checkpoint_restarts_and_says_so(retriever, variant):
    run = _run(variant)
    out = await runtime_for(
        variant,
        _factory(
            FakeChat(heuristic_responder),
            retriever,
            InMemorySaver(),
            InMemoryStateStore(),
            resume=True,
        ),
    ).run(run)
    assert out.status == "completed"
    assert out.resumed is not None
    assert out.resumed.mode == "restart"
    assert out.resumed.checkpoint_id is None


async def test_ordinary_runs_are_not_marked_as_resumed(retriever):
    out = await runtime_for(
        "B",
        _factory(FakeChat(heuristic_responder), retriever, InMemorySaver(), InMemoryStateStore()),
    ).run(_run("B"))
    assert out.resumed is None
    assert all(s.node != RESUME_NODE for s in out.trace)
