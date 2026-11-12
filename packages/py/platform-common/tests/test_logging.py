from __future__ import annotations

import json
import uuid

from bomagent_common.logging import configure_logging, get_logger, redact
from bomagent_common.tenancy import TenantContext, tenant_scope


def test_redact_drops_content_and_masks_secrets():
    event = {
        "event": "x",
        "prompt": "secret design",
        "api_key": "sk-123",
        "db_password": "p",
        "nested": {"Authorization": "Bearer abc", "ok": 1},
        "count": 3,
    }
    out = redact(None, "info", event)
    assert out["prompt"] == "[redacted]"
    assert out["api_key"] == "***"
    assert out["db_password"] == "***"
    assert out["nested"] == {"Authorization": "***", "ok": 1}
    assert out["count"] == 3


def test_redact_handles_lists_and_key_suffixes():
    out = redact(
        None,
        "info",
        {
            "items": [{"token": "t", "n": 1}, ("x", {"private_key": "k"})],
            "aws_secret_access_key": "s",
            "x-api-key": "k",
            "dsn": "postgresql://u:p@h/db",
        },
    )
    assert out["items"][0] == {"token": "***", "n": 1}
    assert out["items"][1][1] == {"private_key": "***"}
    assert out["aws_secret_access_key"] == "***"
    assert out["x-api-key"] == "***"
    assert out["dsn"] == "***"


def test_json_log_contains_tenant_and_no_content(capsys):
    configure_logging("svc-test", level="INFO", json=True)
    ctx = TenantContext(tenant_id=uuid.uuid4(), actor_id="u")
    with tenant_scope(ctx):
        get_logger("t").info("hello", content="CONFIDENTIAL", items=2)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["tenant_id"] == str(ctx.tenant_id)
    assert record["service"] == "svc-test"
    assert "CONFIDENTIAL" not in line
