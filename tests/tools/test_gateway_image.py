"""The LLM gateway image must serve IPv4 (AWS VPC) and IPv6 (Fly 6PN) - ops review I2.

The runtime check is the PR CI step that starts the image on an IPv6-enabled Docker network
and probes both families; this keeps the Dockerfile from silently going single-stack again."""

from __future__ import annotations

import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "deploy/docker/llm-gateway.Dockerfile"


def _cmd() -> list[str]:
    match = re.search(r"^CMD (\[.*\])$", DOCKERFILE.read_text(), re.MULTILINE)
    assert match, "the gateway Dockerfile needs an exec-form CMD"
    return list(json.loads(match.group(1)))


def test_gateway_binds_every_address_family():
    cmd = _cmd()
    host = cmd[cmd.index("--host") + 1]
    # "" = asyncio binds 0.0.0.0 and :: (two sockets); "::" alone is IPv6-only (V6ONLY) and
    # "0.0.0.0" alone is IPv4-only
    assert host == ""
    assert cmd[cmd.index("--num_workers") + 1] == "1"  # the multi-worker path binds differently


def test_gateway_image_has_a_health_check_on_ipv4():
    text = DOCKERFILE.read_text()
    assert "HEALTHCHECK" in text
    assert "http://127.0.0.1:4000/health/liveliness" in text
