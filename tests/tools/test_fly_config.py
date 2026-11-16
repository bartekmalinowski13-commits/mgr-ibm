"""deploy/supabase/fly.toml: web and worker process groups are wired consistently (ARCH-02)."""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "deploy" / "supabase" / "fly.toml"


def load() -> dict:
    return tomllib.loads(CONFIG.read_text())


def test_two_process_groups_with_matching_roles():
    cfg = load()
    assert set(cfg["processes"]) == {"web", "worker"}
    for group, command in cfg["processes"].items():
        assert f"BOMAGENT_ROLE={group}" in command
        assert command.rstrip().endswith("python -m bomagent_allinone serve")
    assert "BOMAGENT_ROLE" not in cfg["env"]  # the role is a per-group setting only


def test_only_the_web_group_is_public_and_it_never_stops():
    cfg = load()
    http = cfg["http_service"]
    assert http["processes"] == ["web"]
    assert http["auto_stop_machines"] == "off"  # relay, reaper and anchors run in web
    assert http["min_machines_running"] >= 1
    assert "services" not in cfg  # no other public service: the worker has no public port


def test_the_worker_group_has_its_own_health_check():
    checks = load()["checks"]
    worker = [c for c in checks.values() if c.get("processes") == ["worker"]]
    assert len(worker) == 1
    assert worker[0]["path"] == "/readyz"
    assert worker[0]["port"] == 8000


def test_every_group_has_a_vm_size_and_the_migration_runs_once_per_release():
    cfg = load()
    assert sorted(p for vm in cfg["vm"] for p in vm["processes"]) == ["web", "worker"]
    assert cfg["deploy"]["release_command"] == "python -m bomagent_allinone migrate"


def test_the_worker_gets_a_smaller_database_pool():
    command = load()["processes"]["worker"]
    assert "BOMAGENT_DB_POOL_SIZE=3" in command


def test_no_secret_is_in_the_env_table():
    for name, value in load()["env"].items():
        assert not any(w in name.upper() for w in ("PASSWORD", "SECRET", "TOKEN")), name
        assert not str(value).startswith(("sk-", "eyJ")), name  # LiteLLM keys, JWTs
        assert "service_role" not in str(value), name
