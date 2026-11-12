"""LangGraph checkpoints in PostgreSQL, scoped to one tenant (ADR-0007, migration 0012).

The saver is bound to a tenant when it is created; every read and write runs in
:func:`tenant_transaction`, so RLS on ``runs.graph_checkpoints`` / ``runs.graph_writes``
decides what is visible. The LangGraph ``thread_id`` is the run id (a ``runs.runs`` row of
the same tenant - checkpoints are deleted with their run).

Checkpoints are stored whole (channel values included) with LangGraph's serializer; a
BOM run has a few dozen checkpoints, so per-channel blob deduplication is not worth it.
Only the async API is implemented - the runtimes call ``ainvoke``.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import tenant_transaction

_SELECT = (
    "SELECT checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint,"
    " metadata_type, metadata FROM runs.graph_checkpoints"
    " WHERE run_id = :r AND checkpoint_ns = :ns"
)

_INSERT_WRITES = (
    "INSERT INTO runs.graph_writes (tenant_id, run_id, checkpoint_ns, checkpoint_id, task_id,"
    " idx, channel, value_type, value, task_path) VALUES (app.current_tenant_id(), :r, :ns,"
    " :c, :t, :i, :ch, :vt, :v, :tp) ON CONFLICT (tenant_id, run_id, checkpoint_ns,"
    " checkpoint_id, task_id, idx) "
)
_KEEP_WRITES = _INSERT_WRITES + "DO NOTHING"
_UPSERT_WRITES = _INSERT_WRITES + (
    "DO UPDATE SET channel = EXCLUDED.channel, value_type = EXCLUDED.value_type,"
    " value = EXCLUDED.value"
)


class TenantCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
        # strict deserialisation: only LangGraph's safe types are rebuilt from the bytes
        # (no import of arbitrary classes, no pickle) - the state is plain dicts and lists
        super().__init__(serde=JsonPlusSerializer(allowed_msgpack_modules=None))
        self.engine, self.tenant_id = engine, tenant_id

    @staticmethod
    def _keys(config: RunnableConfig) -> tuple[uuid.UUID, str]:
        conf = config["configurable"]
        return uuid.UUID(str(conf["thread_id"])), str(conf.get("checkpoint_ns", ""))

    async def _tuple(self, conn: Any, run_id: uuid.UUID, row: Any) -> CheckpointTuple:
        writes = await conn.execute(
            text(
                "SELECT task_id, channel, value_type, value FROM runs.graph_writes"
                " WHERE run_id = :r AND checkpoint_ns = :ns AND checkpoint_id = :c"
                " ORDER BY task_path, task_id, idx"
            ),
            {"r": run_id, "ns": row.checkpoint_ns, "c": row.checkpoint_id},
        )

        def conf(checkpoint_id: str) -> RunnableConfig:
            return {
                "configurable": {
                    "thread_id": str(run_id),
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            }

        return CheckpointTuple(
            config=conf(row.checkpoint_id),
            checkpoint=self.serde.loads_typed((row.checkpoint_type, bytes(row.checkpoint))),
            metadata=self.serde.loads_typed((row.metadata_type, bytes(row.metadata))),
            parent_config=conf(row.parent_checkpoint_id) if row.parent_checkpoint_id else None,
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.value_type, bytes(w.value))))
                for w in writes
            ],
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        run_id, ns = self._keys(config)
        checkpoint_id = get_checkpoint_id(config)
        sql = _SELECT + (
            " AND checkpoint_id = :c" if checkpoint_id else " ORDER BY checkpoint_id DESC LIMIT 1"
        )
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            row = (
                await conn.execute(text(sql), {"r": run_id, "ns": ns, "c": checkpoint_id})
            ).first()
            return await self._tuple(conn, run_id, row) if row else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - LangGraph's signature
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return  # listing across runs is not offered: a saver serves one run at a time
        run_id, ns = self._keys(config)
        sql, params = _SELECT, {"r": run_id, "ns": ns}
        if before is not None and (before_id := get_checkpoint_id(before)):
            sql, params = sql + " AND checkpoint_id < :b", params | {"b": before_id}
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            rows = (await conn.execute(text(sql + " ORDER BY checkpoint_id DESC"), params)).all()
            found = 0
            for row in rows:
                item = await self._tuple(conn, run_id, row)
                if filter and any(item.metadata.get(k) != v for k, v in filter.items()):
                    continue
                yield item
                found += 1
                if limit is not None and found >= limit:
                    return

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        run_id, ns = self._keys(config)
        cp_type, cp_bytes = self.serde.dumps_typed(checkpoint)
        md_type, md_bytes = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO runs.graph_checkpoints (tenant_id, run_id, checkpoint_ns,"
                    " checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint,"
                    " metadata_type, metadata) VALUES (app.current_tenant_id(), :r, :ns, :c,"
                    " :p, :ct, :cb, :mt, :mb) ON CONFLICT (tenant_id, run_id, checkpoint_ns,"
                    " checkpoint_id) DO UPDATE SET checkpoint_type = EXCLUDED.checkpoint_type,"
                    " checkpoint = EXCLUDED.checkpoint, metadata_type = EXCLUDED.metadata_type,"
                    " metadata = EXCLUDED.metadata"
                ),
                {
                    "r": run_id,
                    "ns": ns,
                    "c": checkpoint["id"],
                    "p": config["configurable"].get("checkpoint_id"),
                    "ct": cp_type,
                    "cb": cp_bytes,
                    "mt": md_type,
                    "mb": md_bytes,
                },
            )
        return {
            "configurable": {
                "thread_id": str(run_id),
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        run_id, ns = self._keys(config)
        rows = []
        for i, (channel, value) in enumerate(writes):
            value_type, value_bytes = self.serde.dumps_typed(value)
            rows.append(
                {
                    "r": run_id,
                    "ns": ns,
                    "c": config["configurable"]["checkpoint_id"],
                    "t": task_id,
                    "i": WRITES_IDX_MAP.get(channel, i),
                    "ch": channel,
                    "vt": value_type,
                    "v": value_bytes,
                    "tp": task_path,
                }
            )
        if not rows:
            return
        # regular writes are kept once (a retried task does not overwrite them); special
        # channels (errors, interrupts: negative idx) take the latest value
        keep = [r for r in rows if r["i"] >= 0]
        upsert = [r for r in rows if r["i"] < 0]
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            if keep:
                await conn.execute(text(_KEEP_WRITES), keep)
            if upsert:
                await conn.execute(text(_UPSERT_WRITES), upsert)

    async def adelete_thread(self, thread_id: str) -> None:
        run_id = uuid.UUID(str(thread_id))
        async with tenant_transaction(self.engine, self.tenant_id) as conn:
            for table in ("runs.graph_writes", "runs.graph_checkpoints"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE run_id = :r"),  # noqa: S608 - fixed names
                    {"r": run_id},
                )

    def get_next_version(self, current: str | None, channel: None) -> str:
        """Same scheme as LangGraph's savers: monotonic counter + random suffix."""
        current_v = 0 if current is None else int(str(current).split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"  # noqa: S311 - not security
