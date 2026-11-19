"""The nightly real-model evaluation must default to a model the CLI accepts (ops review I8):
a disabled or unverified default fails every scheduled run for a config reason."""

from __future__ import annotations

from pathlib import Path

import yaml

from bomagent_llm.catalog import load_catalog

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/nightly-evals.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_default_model_is_an_enabled_verified_real_chat_model():
    wf = _workflow()
    on = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    default = on["workflow_dispatch"]["inputs"]["model"]["default"]
    spec = load_catalog().get(default, allow_local=False)  # raises when not allowed
    assert "chat" in spec.capabilities
    assert spec.provider != "fake"


def test_scheduled_runs_use_the_same_default():
    wf = _workflow()
    on = wf.get("on", wf.get(True))
    default = on["workflow_dispatch"]["inputs"]["model"]["default"]
    model_env = wf["jobs"]["real-model-evals"]["env"]["MODEL"]
    assert model_env == f"${{{{ inputs.model || '{default}' }}}}"
