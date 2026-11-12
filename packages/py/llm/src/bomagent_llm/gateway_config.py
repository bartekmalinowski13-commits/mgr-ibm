"""Render the cloud LiteLLM configuration from the model catalogue (ADR-0006).

Only models that are enabled *and* verified for EU processing are exposed by the
gateway; local fakes never are. Bedrock authenticates with the task role (no keys);
providers that need keys reference environment variables injected by ECS from
Secrets Manager - no secret is ever written into the file.

    python -m bomagent_llm.gateway_config --region eu-central-1 > config.yaml
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import yaml

from bomagent_llm.catalog import Catalog, ModelSpec, load_catalog
from bomagent_llm.eu_guard import (
    MISTRAL_EU_BASE,
    assert_eu_only,
    check_catalog,
    check_gateway_config,
)

KEY_ENV = {
    "azure_openai": ("AZURE_API_KEY", "AZURE_API_BASE"),
    "mistral": ("MISTRAL_API_KEY", None),
}


def _entry(model: ModelSpec, region: str) -> dict[str, Any] | None:
    params: dict[str, Any] = {"model": model.gateway_model}
    if model.provider == "bedrock":
        params["aws_region_name"] = model.region or region
    elif model.provider in KEY_ENV:
        key, base = KEY_ENV[model.provider]
        params["api_key"] = f"os.environ/{key}"
        if base:
            params["api_base"] = f"os.environ/{base}"
        elif model.provider == "mistral":
            params["api_base"] = MISTRAL_EU_BASE  # not the default api.mistral.ai
    else:  # local, self-hosted or unknown providers are not served by the cloud gateway
        return None
    info: dict[str, Any] = {
        "license_class": model.license_class.value,
        "residency": model.residency,
        "provider": model.provider,
        "region": model.region,
    }
    if "embedding" in model.capabilities:
        info["mode"] = "embedding"
    return {"model_name": model.gateway_model, "litellm_params": params, "model_info": info}


def render(catalog: Catalog, *, region: str) -> dict[str, Any]:
    entries = [
        e
        for m in catalog.models
        if m.enabled and m.verified and m.residency != "local"
        for e in [_entry(m, region)]
        if e is not None
    ]
    config = {
        "model_list": entries,
        "litellm_settings": {"drop_params": True, "telemetry": False, "request_timeout": 120},
        "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
    }
    # fail closed: a non-EU region, profile or endpoint must never reach the gateway
    assert_eu_only(check_catalog(catalog) + check_gateway_config(config))
    return config


def main() -> None:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(prog="bomagent-gateway-config")
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()
    yaml.safe_dump(render(load_catalog(), region=args.region), sys.stdout, sort_keys=False)


if __name__ == "__main__":  # pragma: no cover
    main()
