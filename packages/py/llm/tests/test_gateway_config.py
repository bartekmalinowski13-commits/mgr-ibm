"""Rendering the cloud LiteLLM config from the model catalogue."""

from __future__ import annotations

from bomagent_llm.catalog import load_catalog
from bomagent_llm.gateway_config import render


def _catalog_with(enabled: set[str]):
    catalog = load_catalog()
    models = [
        m.model_copy(update={"enabled": m.id in enabled, "verified": m.id in enabled})
        for m in catalog.models
    ]
    return catalog.model_copy(update={"models": models})


def test_only_enabled_verified_eu_models_are_rendered():
    config = render(_catalog_with({"claude-sonnet-eu", "fake-closed"}), region="eu-central-1")
    names = [m["model_name"] for m in config["model_list"]]
    assert names == ["bedrock/eu.anthropic.claude-sonnet-5-5"]  # local fakes never reach the cloud
    entry = config["model_list"][0]
    assert entry["litellm_params"] == {
        "model": "bedrock/eu.anthropic.claude-sonnet-5-5",
        "aws_region_name": "eu-central-1",
    }
    assert "api_key" not in str(config)  # Bedrock authenticates with the task role


def test_key_based_providers_reference_environment_variables_only():
    config = render(_catalog_with({"openai-eu", "mistral-large-eu"}), region="eu-central-1")
    text = str(config)
    assert "os.environ/" in text
    for entry in config["model_list"]:
        key = entry["litellm_params"].get("api_key", "")
        assert key.startswith("os.environ/"), entry
    assert config["litellm_settings"]["drop_params"] is True


def test_nothing_enabled_renders_an_empty_but_valid_config():
    config = render(_catalog_with(set()), region="eu-central-1")
    assert config["model_list"] == []
    assert config["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"
