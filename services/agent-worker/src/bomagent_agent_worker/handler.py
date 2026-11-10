"""Execute BOM runs announced on the ``runs`` queue.

Message ``run.requested`` (tenant scope), payload::

    {"run_id": uuid, "variant": "A"|"B"|"A-sdk", "model_id": str,
     "design_key": "tenants/<tenant>/.../parsed_design.json",
     "requirements": {...}, "kb_snapshot_id": str | null, "budget": {...} | null}

The parsed design is read from the tenant's object prefix (a key outside the prefix is
rejected), the runtime runs with knowledge-base access confined to the tenant (RLS), and
``bom.json`` + ``result.json`` (trace, usage, config) are written next to it under
``tenants/<tenant>/runs/<run_id>/``. Persisting run rows and audit events belongs to the
API module (M4), which will consume ``run.completed`` events.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from bomagent_agents import Budget, Dependencies, Retriever, RunConfig, get_runtime
from bomagent_bom.model import ParsedDesign, Requirements
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, key_belongs_to, tenant_key
from bomagent_llm.catalog import Catalog
from bomagent_llm.chat import ChatClient

log = get_logger(__name__)
RUN_REQUESTED = "run.requested"


class RejectedMessageError(ValueError):
    """A message that must never be processed (foreign object key, bad payload)."""


@dataclass
class RunExecutor:
    chat: ChatClient
    catalog: Catalog
    store: ObjectStore
    retriever_for: Callable[[uuid.UUID, str | None], Retriever]
    allow_local_models: bool = False

    async def handle(self, message: Message) -> None:
        if message.type != RUN_REQUESTED:
            log.warning("message_type_ignored", message_type=message.type)
            return
        p = message.payload
        try:
            run_id = uuid.UUID(str(p["run_id"]))
            design_key = str(p["design_key"])
            variant = str(p.get("variant", "B"))
            model_id = str(p["model_id"])
        except (KeyError, ValueError) as exc:
            raise RejectedMessageError(f"invalid run.requested payload: {exc}") from exc
        if not key_belongs_to(message.tenant_id, design_key):
            raise RejectedMessageError("design key outside the tenant prefix")

        spec = self.catalog.get(model_id, allow_local=self.allow_local_models)
        design = ParsedDesign.model_validate_json(await self.store.get(design_key))
        requirements = Requirements.model_validate(p.get("requirements") or {})
        config = RunConfig(
            run_id=run_id,
            tenant_id=str(message.tenant_id),
            variant=variant,
            model_id=spec.id,
            kb_snapshot_id=p.get("kb_snapshot_id"),
            budget=Budget.model_validate(p.get("budget") or {}),
        )
        deps = Dependencies(
            chat=self.chat,
            model=spec,
            retriever=self.retriever_for(message.tenant_id, config.kb_snapshot_id),
        )
        result = await get_runtime(variant).run(design, requirements, config, deps)
        prefix = ("runs", str(run_id))
        if result.bom is not None:
            await self.store.put(
                tenant_key(message.tenant_id, *prefix, "bom.json"),
                result.bom.model_dump_json(indent=1).encode(),
                "application/json",
            )
        await self.store.put(
            tenant_key(message.tenant_id, *prefix, "result.json"),
            result.model_dump_json(indent=1, exclude={"bom"}).encode(),
            "application/json",
        )
        log.info(
            "run_finished",
            run_id=str(run_id),
            variant=variant,
            model=spec.id,
            status=result.status,
            llm_calls=result.usage.llm_calls,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
