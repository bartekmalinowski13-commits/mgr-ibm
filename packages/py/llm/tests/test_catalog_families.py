"""Catalogue entries of every model family and the local-only override."""

from __future__ import annotations

from pathlib import Path

import pytest

from bomagent_llm.catalog import ModelNotAllowedError, load_catalog

OLLAMA = {
    "ollama-qwen3-8b": "qwen3:8b",
    "ollama-qwen3-14b": "qwen3:14b",
    "ollama-llama3-1-8b": "llama3.1:8b",
    "ollama-mistral-small": "mistral-small:24b",
    "ollama-ministral-3-8b": "ministral-3:8b",
    "ollama-gpt-oss-20b": "gpt-oss:20b",
}
HOSTED_OPEN = {
    "qwen3-235b-bedrock-eu": "bedrock",
    "gpt-oss-120b-bedrock-eu": "bedrock",
    "ministral-8b-mistral-eu": "mistral",
    "mistral-small-mistral-eu": "mistral",
}


def test_every_new_entry_is_disabled_unverified_and_documented():
    catalog = load_catalog()
    by_id = {m.id: m for m in catalog.models}
    for model_id in [*OLLAMA, *HOSTED_OPEN]:
        spec = by_id[model_id]
        assert spec.enabled is False
        assert spec.verified is False
        assert spec.license_class.value == "open-weight"
        assert spec.notes, model_id


def test_local_entries_use_the_ollama_tag_and_mention_memory():
    by_id = {m.id: m for m in load_catalog().models}
    for model_id, tag in OLLAMA.items():
        spec = by_id[model_id]
        assert spec.provider == "ollama"
        assert spec.residency == "local"
        assert spec.gateway_model == tag
        assert "GB" in spec.notes


def test_hosted_open_weight_entries_are_eu_only():
    by_id = {m.id: m for m in load_catalog().models}
    for model_id, provider in HOSTED_OPEN.items():
        spec = by_id[model_id]
        assert spec.provider == provider
        assert spec.residency in {"eu-region", "eu-geo"}
    assert by_id["gpt-oss-120b-bedrock-eu"].gateway_model == "bedrock/openai.gpt-oss-120b-1:0"
    assert not any("dashscope" in m.gateway_model for m in by_id.values())


def test_disabled_local_entries_are_refused():
    with pytest.raises(ModelNotAllowedError, match="disabled"):
        load_catalog().get("ollama-qwen3-8b")


def _override(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "override.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_local_override_enables_a_local_entry_without_touching_models_yaml(tmp_path):
    path = _override(tmp_path, "enable: [ollama-qwen3-8b]\n")
    catalog = load_catalog(override=path)
    assert catalog.get("ollama-qwen3-8b").gateway_model == "qwen3:8b"
    with pytest.raises(ModelNotAllowedError, match="local development only"):
        catalog.get("ollama-qwen3-8b", allow_local=False)
    # the shipped file is untouched
    with pytest.raises(ModelNotAllowedError):
        load_catalog().get("ollama-qwen3-8b")


def test_override_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BOMAGENT_CATALOG_OVERRIDE", str(_override(tmp_path, "enable: [ollama-qwen3-14b]"))
    )
    assert load_catalog().get("ollama-qwen3-14b").provider == "ollama"


@pytest.mark.parametrize(
    "model_id", ["claude-sonnet-eu", "mistral-large-eu", "qwen3-235b-bedrock-eu"]
)
def test_override_can_never_enable_a_hosted_model(tmp_path, model_id):
    with pytest.raises(ValueError, match="local"):
        load_catalog(override=_override(tmp_path, f"enable: [{model_id}]"))


def test_override_with_an_unknown_id_fails(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        load_catalog(override=_override(tmp_path, "enable: [nope]"))
