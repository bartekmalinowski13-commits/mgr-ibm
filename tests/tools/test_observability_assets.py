"""deploy/observability: dashboards and alert rules only use metrics the code really records."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "deploy" / "observability"
METRICS_PY = ROOT / "packages" / "py" / "platform-common" / "src" / "bomagent_common" / "metrics.py"

# what the OTel auto-instrumentation (FastAPI, SQLAlchemy) adds; not defined in our code
EXTERNAL = re.compile(r"^(http_server_|http_client_|db_client_|up$|fly_)")
SUFFIXES = ("_bucket", "_sum", "_count")


def defined_metrics() -> set[str]:
    return set(re.findall(r'"(bomagent_[a-z0-9_]+)"', METRICS_PY.read_text()))


def names_in(expr: str) -> set[str]:
    return set(re.findall(r"\b([a-z][a-z0-9_]*)\s*(?:\{|\[|\)|$|\s)", expr)) & {
        n for n in re.findall(r"\b[a-z][a-z0-9_]*\b", expr) if n.startswith(("bomagent_", "http_"))
    }


def base(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return name


def check(expr: str, where: str) -> None:
    known = defined_metrics()
    for name in names_in(expr):
        if EXTERNAL.match(name):
            continue
        assert base(name) in known, f"{where}: {name} is not a metric of metrics.py"


def test_the_code_defines_the_metrics_the_audit_asks_for():
    assert {
        "bomagent_runs_total",
        "bomagent_run_duration_s",
        "bomagent_llm_tokens_total",
        "bomagent_llm_cost_eur_total",
        "bomagent_parse_total",
        "bomagent_outbox_dead_total",
        "bomagent_queue_dead_total",
    } <= defined_metrics()


def test_the_dashboard_is_valid_and_queries_known_metrics():
    dash = json.loads((OBS / "dashboards" / "bomagent-overview.json").read_text())
    assert dash["title"]
    assert dash["panels"]
    exprs = [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    assert len(exprs) >= 8
    for expr in exprs:
        check(expr, "dashboard")


def test_every_alert_has_what_an_on_call_needs():
    doc = yaml.safe_load((OBS / "alerts.yml").read_text())
    rules = [r for g in doc["groups"] for r in g["rules"]]
    assert len(rules) >= 6
    names = [r["alert"] for r in rules]
    assert len(names) == len(set(names))
    for r in rules:
        assert r["expr"], r["alert"]
        assert r["labels"]["severity"] in {"page", "ticket"}, r["alert"]
        assert r["annotations"]["summary"], r["alert"]
        assert r["annotations"]["runbook"].startswith("docs/"), r["alert"]
        assert (ROOT / r["annotations"]["runbook"].split("#")[0]).exists(), r["alert"]
        check(r["expr"], r["alert"])


def test_the_alerts_cover_the_audit_list():
    doc = yaml.safe_load((OBS / "alerts.yml").read_text())
    text = json.dumps(doc)
    for needle in (
        "bomagent_queue_dead_total",  # dead letters
        "bomagent_outbox_dead_total",  # dead outbox rows
        "bomagent_runs_total",  # run failure rate
        "http_server",  # 5xx rate
    ):
        assert needle in text, needle
