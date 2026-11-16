"""ARCH-08: the gateway image verifies its environment is EU-only before LiteLLM starts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gateway_image_checks_the_environment_before_starting_litellm():
    dockerfile = (ROOT / "deploy/docker/llm-gateway.Dockerfile").read_text(encoding="utf-8")
    script = (ROOT / "deploy/gateway/entrypoint.sh").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/app/entrypoint.sh"]' in dockerfile
    assert "/opt/eu-guard/bomagent_llm" in dockerfile
    assert "set -eu" in script  # a failing check stops the start
    assert script.index("bomagent_llm.eu_guard") < script.index('exec litellm "$@"')
