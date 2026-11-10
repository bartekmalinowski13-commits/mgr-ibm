from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from bomagent_agent_worker.app import Settings, build_handler, create_app
from bomagent_agent_worker.handler import RejectedMessageError, RunExecutor
from bomagent_agents import StaticRetriever
from bomagent_agents.simulators import simulate
from bomagent_cad import FileRef, parse_files
from bomagent_common.messaging import Message
from bomagent_common.storage import InMemoryObjectStore, tenant_key
from bomagent_common.tenancy import TenantContext, tenant_scope
from bomagent_llm.catalog import ModelNotAllowedError, load_catalog
from bomagent_llm.fake import FakeChat

ROOT = Path(__file__).resolve().parents[3] / "evals" / "fixtures"


def _design_json() -> bytes:
    folder = ROOT / "kicad" / "pulse-ox"
    files = [FileRef.from_path(p) for p in sorted(folder.iterdir()) if p.suffix == ".kicad_sch"]
    return parse_files(files).model_dump_json().encode()


def _executor(store: InMemoryObjectStore, allow_local: bool = True) -> RunExecutor:
    retriever = StaticRetriever.from_directory(ROOT / "datasheets")
    return RunExecutor(
        chat=FakeChat(simulate),
        catalog=load_catalog(),
        store=store,
        retriever_for=lambda tenant, snap: retriever,
        allow_local_models=allow_local,
    )


async def _handle(executor: RunExecutor, msg: Message) -> None:
    """Same as the consumer loop: the handler runs inside the message's tenant context."""
    with tenant_scope(msg.tenant_context()):
        await executor.handle(msg)


async def _message(
    store: InMemoryObjectStore,
    variant: str = "B",
    key: str | None = None,
    model: str = "fake-closed",
) -> Message:
    ctx = TenantContext(tenant_id=uuid.uuid4(), actor_id="user-1", actor_type="user")
    design_key = key or tenant_key(ctx.tenant_id, "designs", "d1", "parsed_design.json")
    if key is None:
        with tenant_scope(ctx):
            await store.put(design_key, _design_json())
    payload = {
        "run_id": str(uuid.uuid4()),
        "variant": variant,
        "model_id": model,
        "design_key": design_key,
    }
    return Message.create("run.requested", ctx, payload)


@pytest.mark.parametrize("variant", ["A", "B"])
async def test_run_writes_bom_and_result_under_the_tenant_prefix(variant):
    store = InMemoryObjectStore()
    msg = await _message(store, variant)
    await _handle(_executor(store), msg)
    run_id = msg.payload["run_id"]
    bom = json.loads(store.objects[tenant_key(msg.tenant_id, "runs", run_id, "bom.json")])
    result = json.loads(store.objects[tenant_key(msg.tenant_id, "runs", run_id, "result.json")])
    assert bom["variant"].startswith(variant)
    assert bom["items"]
    assert result["status"] == "completed"
    assert result["config"]["tenant_id"] == str(msg.tenant_id)
    assert "bom" not in result


async def test_foreign_design_key_and_bad_payload_are_rejected():
    store = InMemoryObjectStore()
    other = tenant_key(uuid.uuid4(), "designs", "x.json")
    with pytest.raises(RejectedMessageError, match="outside"):
        await _handle(_executor(store), await _message(store, key=other))
    ctx = TenantContext(tenant_id=uuid.uuid4(), actor_id="u")
    with pytest.raises(RejectedMessageError, match="payload"):
        await _handle(_executor(store), Message.create("run.requested", ctx, {"variant": "A"}))


async def test_local_models_refused_unless_allowed_and_other_types_ignored():
    store = InMemoryObjectStore()
    with pytest.raises(ModelNotAllowedError):
        await _handle(_executor(store, allow_local=False), await _message(store))
    ctx = TenantContext(tenant_id=uuid.uuid4(), actor_id="u")
    await _handle(_executor(store), Message.create("something.else", ctx, {}))


def test_build_handler_requires_configuration():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        build_handler(Settings())
    with pytest.raises(RuntimeError, match="GATEWAY"):
        build_handler(Settings(database_url="postgresql+psycopg://u:p@localhost/db"))
    with pytest.raises(RuntimeError, match="not allowed"):
        build_handler(
            Settings(
                database_url="postgresql+psycopg://u:p@localhost/db",
                llm_gateway_url="http://gw",
                llm_gateway_key="k",
                allow_local_models=True,
                environment="prod",
            )
        )
    handler = build_handler(
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            llm_gateway_url="http://gw",
            llm_gateway_key="k",
        )
    )
    assert callable(handler)
    assert create_app(Settings()) is not None
