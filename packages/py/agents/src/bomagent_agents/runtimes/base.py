"""Variant runtime contract and the agent steps shared by variants A and B (ADR-0007).

Both variants take the same input (``ParsedDesign`` + ``Requirements`` + ``RunConfig``)
and return the same output (``RunResult``: ``BomVersion`` + trace + usage). They share the
part-selection agent and the knowledge base, so differences in the results come from the
architecture, not from different building blocks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bomagent_agents.context import AgentLLM, RunConfig, RunState, TraceStep
from bomagent_agents.prompts import SELECT, excerpts_block
from bomagent_agents.retrieval import Excerpt, Retriever, norm_mpn
from bomagent_agents.schemas import PartSelection
from bomagent_bom.model import BomItem, BomVersion, ParsedDesign, Requirements, Usage
from bomagent_llm.catalog import ModelSpec
from bomagent_llm.chat import ChatClient


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed"] = "completed"
    error: str | None = None
    bom: BomVersion | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    config: RunConfig
    model: dict[str, str] = Field(default_factory=dict)


@dataclass
class Dependencies:
    """What a runtime needs from the outside world (injected, never global)."""

    chat: ChatClient
    model: ModelSpec
    retriever: Retriever


class VariantRuntime(Protocol):
    name: str

    async def run(
        self,
        design: ParsedDesign,
        requirements: Requirements,
        config: RunConfig,
        deps: Dependencies,
    ) -> RunResult: ...


def line_query(item: BomItem) -> str:
    """Retrieval query for a BOM line (value, package, kind) - deterministic."""
    parts = [
        item.value_normalized or item.value,
        item.package or "",
        item.kind,
        item.description,
        "ordering information part number",
    ]
    return " ".join(p for p in parts if p)


def line_payload(item: BomItem) -> dict[str, object]:
    return {
        "refdes": item.refdes,
        "quantity": item.quantity,
        "kind": item.kind,
        "value": item.value,
        "value_normalized": item.value_normalized,
        "footprint": item.footprint,
        "package": item.package,
        "mpn": item.mpn,
        "manufacturer": item.manufacturer,
        "description": item.description,
        "dnp": item.dnp,
    }


async def select_parts(
    items: list[BomItem],
    targets: list[int],
    requirements: Requirements,
    llm: AgentLLM,
    retriever: Retriever,
    state: RunState,
    *,
    agent: str,
    feedback: dict[int, str] | None = None,
) -> dict[int, tuple[PartSelection, list[Excerpt]]]:
    """Part-selection agent, fan-out over ``targets`` (indices into ``items``) with the
    run's concurrency limit. Retrieval is batched in one call."""
    if not targets:
        return {}
    cfg = state.config
    queries = [line_query(items[i]) for i in targets]
    hits_per_line = await retriever.search_many(queries, cfg.kb_top_k)
    sem = asyncio.Semaphore(cfg.concurrency)
    req = requirements.model_dump(mode="json")

    async def one(idx: int, hits: list[Excerpt]) -> tuple[int, tuple[PartSelection, list[Excerpt]]]:
        async with sem:
            sel = await llm.structured(
                SELECT,
                agent,
                PartSelection,
                line=line_payload(items[idx]),
                requirements=req,
                feedback=(feedback or {}).get(idx, ""),
                excerpts=excerpts_block([(h.chunk_id, h.title, h.content) for h in hits]),
            )
            return idx, (sel, hits)

    pairs = await asyncio.gather(*(one(i, h) for i, h in zip(targets, hits_per_line, strict=True)))
    return dict(pairs)


def apply_selection(
    item: BomItem, sel: PartSelection, hits: list[Excerpt], llm: AgentLLM, agent: str
) -> BomItem:
    """Write a selection into a BOM line with agent provenance and citations."""
    if not sel.mpn:
        return item
    cited = [h for h in hits if h.chunk_id in set(sel.cited_chunks)] or [
        h for h in hits if norm_mpn(sel.mpn) in norm_mpn(h.content)
    ]
    prov = llm.provenance(agent, SELECT, [h.citation() for h in cited[:3]], sel.rationale)
    provenance = dict(item.provenance)
    provenance["mpn"] = prov
    if sel.manufacturer:
        provenance["manufacturer"] = prov
    return item.model_copy(
        update={
            "mpn": sel.mpn.strip(),
            "manufacturer": sel.manufacturer.strip() or item.manufacturer,
            "description": item.description or sel.description,
            "provenance": provenance,
        }
    )


def model_info(spec: ModelSpec) -> dict[str, str]:
    return {
        "id": spec.id,
        "gateway_model": spec.gateway_model,
        "provider": spec.provider,
        "license_class": spec.license_class.value,
        "residency": spec.residency,
    }
