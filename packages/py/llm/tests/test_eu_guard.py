"""EU-only enforcement for the catalogue and the rendered gateway configuration."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from bomagent_llm.catalog import Catalog, ModelSpec, load_catalog
from bomagent_llm.eu_guard import (
    EuResidencyError,
    check_catalog,
    check_gateway_config,
)
from bomagent_llm.gateway_config import render


def _spec(**over: Any) -> ModelSpec:
    base: dict[str, Any] = {
        "id": "m",
        "gateway_model": "bedrock/eu.anthropic.claude-sonnet-5-5",
        "provider": "bedrock",
        "license_class": "closed",
        "residency": "eu-geo",
        "region": "eu-central-1",
        "capabilities": ["chat"],
        "enabled": True,
        "verified": True,
    }
    return ModelSpec.model_validate(base | over)


def _catalog(*specs: ModelSpec) -> Catalog:
    return Catalog(models=list(specs))


def _all_enabled() -> Catalog:
    catalog = load_catalog()
    models = [
        m.model_copy(update={"enabled": True, "verified": True})
        for m in catalog.models
        if m.provider in {"bedrock", "azure_openai", "mistral"}
    ]
    return Catalog(models=models)


def test_shipped_catalogue_is_clean_even_with_everything_enabled():
    assert check_catalog(_all_enabled()) == []
    config = render(_all_enabled(), region="eu-central-1")
    assert check_gateway_config(config) == []
    assert config["model_list"], "the fixture must actually render models"


def test_shipped_catalogue_enables_only_local_entries():
    enabled = [m.id for m in load_catalog().models if m.enabled]
    assert all(m.startswith("fake-") for m in enabled)


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"region": "us-east-1"}, "us-east-1"),
        ({"gateway_model": "bedrock/us.anthropic.claude-sonnet-5-5"}, "us."),
        ({"gateway_model": "bedrock/global.anthropic.claude-sonnet-5-5"}, "global."),
        ({"gateway_model": "bedrock/apac.anthropic.claude-sonnet-5-5"}, "apac."),
        ({"region": "eu-west-2"}, "eu-west-2"),  # London is not in the EU
        ({"region": "eu-central-2"}, "eu-central-2"),  # Zurich is not in the EU
        ({"region": None, "gateway_model": "bedrock/anthropic.claude-x"}, "region"),
    ],
)
def test_bedrock_violations_are_reported(over, needle):
    problems = check_catalog(_catalog(_spec(**over)))
    assert problems
    assert any(needle in p for p in problems), problems


def test_bedrock_in_region_model_in_an_eu_region_is_fine():
    spec = _spec(gateway_model="bedrock/qwen.qwen3-235b-a22b-2507-v1:0", region="eu-north-1")
    assert check_catalog(_catalog(spec)) == []


def test_azure_needs_an_eu_region_and_mistral_needs_none():
    azure = _spec(
        gateway_model="azure/dep", provider="azure_openai", region="eastus", residency="eu-geo"
    )
    assert any("eastus" in p for p in check_catalog(_catalog(azure)))
    ok = azure.model_copy(update={"region": "swedencentral"})
    assert check_catalog(_catalog(ok)) == []
    mistral = _spec(
        gateway_model="mistral/mistral-large-latest",
        provider="mistral",
        region=None,
        residency="eu-region",
    )
    assert check_catalog(_catalog(mistral)) == []


def test_foreign_providers_cannot_be_enabled():
    spec = _spec(gateway_model="dashscope/qwen-max", provider="alibaba", region=None)
    assert any("provider" in p for p in check_catalog(_catalog(spec)))


def test_disabled_entries_are_not_checked():
    bad = _spec(region="us-east-1", enabled=False, verified=False)
    assert check_catalog(_catalog(bad)) == []


def _config() -> dict[str, Any]:
    return copy.deepcopy(render(_all_enabled(), region="eu-central-1"))


def _first(config: dict[str, Any], provider: str) -> dict[str, Any]:
    return next(e for e in config["model_list"] if e["model_info"]["provider"] == provider)


def test_rendered_config_rejects_us_region_and_us_profile():
    config = _config()
    _first(config, "bedrock")["litellm_params"]["aws_region_name"] = "us-east-1"
    assert any("us-east-1" in p for p in check_gateway_config(config))
    config = _config()
    _first(config, "bedrock")["litellm_params"]["model"] = "bedrock/us.anthropic.claude-x"
    assert any("us." in p for p in check_gateway_config(config))


@pytest.mark.parametrize(
    "base",
    [
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope-intl.aliyuncs.com/v1",
        "https://api.openai.com/v1",
        "https://example.alibabacloud.com",
    ],
)
def test_rendered_config_rejects_foreign_endpoints(base):
    config = _config()
    _first(config, "mistral")["litellm_params"]["api_base"] = base
    assert check_gateway_config(config), base
    config = _config()
    _first(config, "azure_openai")["litellm_params"]["api_base"] = base
    assert check_gateway_config(config), base


def test_rendered_config_accepts_the_documented_endpoints():
    config = _config()
    _first(config, "mistral")["litellm_params"]["api_base"] = "https://api.mistral.ai/v1"
    _first(config, "azure_openai")["litellm_params"]["api_base"] = "https://r.openai.azure.com"
    assert check_gateway_config(config) == []


def test_azure_region_in_the_config_must_be_eu():
    config = _config()
    _first(config, "azure_openai")["model_info"]["region"] = "eastus"
    assert any("eastus" in p for p in check_gateway_config(config))


def test_render_fails_closed_on_a_violation():
    with pytest.raises(EuResidencyError, match="us-east-1"):
        render(_catalog(_spec(region="us-east-1")), region="eu-central-1")
