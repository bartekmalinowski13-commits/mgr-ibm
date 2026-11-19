"""SQLAlchemy tracing is best effort: a change in the instrumentation's private API must
never stop a service from starting (it then runs without database spans)."""

from __future__ import annotations

import pytest
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor, engine
from sqlalchemy.ext.asyncio import create_async_engine
from structlog.testing import capture_logs

from bomagent_common import telemetry


def _boom(*_args: object, **_kwargs: object) -> None:
    raise TypeError("private API changed")


def test_instrumentation_failure_is_logged_once_and_ignored(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(engine, "EngineTracer", _boom)
    monkeypatch.setattr(SQLAlchemyInstrumentor, "instrument", _boom)
    monkeypatch.setattr(telemetry, "_sql_warned", False)
    engines = [create_async_engine("postgresql+psycopg://u:p@localhost:1/db") for _ in range(2)]
    with capture_logs() as logs:
        for e in engines:
            telemetry.instrument_sqlalchemy(e)  # never raises
    warnings = [x for x in logs if x["event"] == "sqlalchemy_instrumentation_unavailable"]
    assert len(warnings) == 1
    assert warnings[0]["log_level"] == "warning"


def test_engines_are_instrumented_once():
    e = create_async_engine("postgresql+psycopg://u:p@localhost:1/db")
    telemetry.instrument_sqlalchemy(e)
    telemetry.instrument_sqlalchemy(e)
    assert e.sync_engine in telemetry._traced_engines
