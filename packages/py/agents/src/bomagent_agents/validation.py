"""The validation stage of each variant on its own (thesis metric "skuteczność walidacji").

The experiment injects known errors into a reference BOM and asks each variant's
validator to review it: variant A's validator agent (LLM, same prompt as in the full
run) and variant B's deterministic rule pack. Scoring is variant-neutral
(``bomagent_eval.injection``). Evaluating the stage on the same input isolates it from
the earlier steps, which differ between the variants.
"""

from __future__ import annotations

import uuid

from bomagent_agents.contracts import RunConfig
from bomagent_agents.retrieval import Retriever
from bomagent_agents.runtime_base import AgentContext
from bomagent_agents.variant_a import llm_validate
from bomagent_bom.model import BomItem, Finding, Requirements
from bomagent_llm.catalog import Catalog, load_catalog
from bomagent_llm.chat import ChatClient
from bomagent_rules import validate


def validation_context(
    chat: ChatClient,
    retriever: Retriever,
    config: RunConfig,
    requirements: Requirements,
    catalog: Catalog | None = None,
) -> AgentContext:
    """Agent context for validation-only calls (own budget, no design MPNs)."""
    return AgentContext(
        chat=chat,
        catalog=catalog or load_catalog(),
        retriever=retriever,
        config=config,
        requirements=requirements,
        run_id=f"validation-{uuid.uuid4()}",
    )


async def validate_bom(variant: str, ctx: AgentContext, items: list[BomItem]) -> list[Finding]:
    """Findings of ``variant``'s validator on ``items``."""
    if variant == "A":
        return await llm_validate(ctx, items, ctx.requirements)
    if variant == "B":
        return validate(items, ctx.requirements).findings
    raise ValueError(f"unknown variant {variant!r}")
