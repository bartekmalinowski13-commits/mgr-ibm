"""EU-only enforcement for the model catalogue and the rendered gateway config (ADR-0006).

CLAUDE.md rule 2: infrastructure and LLM providers process data in the EU only. The
catalogue schema already restricts ``residency``; this module additionally checks what
the gateway would really call - regions, inference-profile prefixes and endpoints - so a
wrong id in ``models.yaml`` fails CI (and the rendering of the config) instead of
silently sending customer data outside the EU.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from bomagent_llm.catalog import ALLOWED_RESIDENCY, Catalog, ModelSpec

#: EU member-state AWS regions (London ``eu-west-2`` and Zurich ``eu-central-2`` are not)
EU_AWS_REGIONS = frozenset(
    {"eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2"}
)
#: Azure regions in EU member states (Norway and Switzerland are not)
EU_AZURE_REGIONS = frozenset(
    {
        "swedencentral",
        "francecentral",
        "germanywestcentral",
        "italynorth",
        "polandcentral",
        "spaincentral",
    }
)
#: providers the cloud gateway may serve; everything else is refused when enabled
ALLOWED_PROVIDERS = frozenset({"bedrock", "azure_openai", "mistral", "vllm", "fake", "ollama"})
#: geographic inference-profile prefixes of Bedrock; only ``eu.`` stays in the EU
_GEO_PREFIXES = frozenset({"us", "us-gov", "global", "apac", "ap", "au", "jp", "ca", "eu"})
_AZURE_HOST_SUFFIXES = (
    ".openai.azure.com",
    ".cognitiveservices.azure.com",
    ".services.ai.azure.com",
)
_BEDROCK_HOST = re.compile(r"^bedrock-runtime\.(?P<region>[a-z0-9-]+)\.amazonaws\.com$")
#: only the regional endpoint guarantees EU inference
#: (docs.mistral.ai/inference/regional-inference);
#: the default api.mistral.ai and api.us.mistral.ai do not
_MISTRAL_HOST = "api.eu.mistral.ai"
MISTRAL_EU_BASE = f"https://{_MISTRAL_HOST}/v1"
_ENV_API_BASE = {"azure_openai": "os.environ/AZURE_API_BASE"}
#: names that must never appear anywhere in a rendered config (no EU processing guarantee)
_FORBIDDEN_MARKERS = ("dashscope", "aliyun", "alibaba", "api.openai.com", "api.anthropic.com")


class EuResidencyError(ValueError):
    """A catalogue entry or gateway config would process data outside the EU."""


def _bedrock_problems(label: str, model: str, region: str | None) -> list[str]:
    problems: list[str] = []
    ident = model.removeprefix("bedrock/")
    prefix = ident.split(".", 1)[0]
    if prefix in _GEO_PREFIXES and prefix != "eu":
        problems.append(f"{label}: inference profile prefix '{prefix}.' is not EU")
    if region is None:
        problems.append(f"{label}: a Bedrock model needs an explicit EU region")
    elif region not in EU_AWS_REGIONS:
        problems.append(f"{label}: Bedrock region {region} is not an allowed EU region")
    return problems


def _azure_problems(label: str, region: str | None) -> list[str]:
    if region not in EU_AZURE_REGIONS:
        return [f"{label}: Azure region {region} is not an allowed EU region"]
    return []


def check_catalog(catalog: Catalog) -> list[str]:
    """Problems of the *enabled* entries (disabled ones may hold placeholders)."""
    problems: list[str] = []
    for m in catalog.models:
        if not m.enabled:
            continue
        label = f"model {m.id}"
        if m.residency not in ALLOWED_RESIDENCY:
            problems.append(f"{label}: residency {m.residency} is not allowed")
        if m.provider not in ALLOWED_PROVIDERS:
            problems.append(f"{label}: provider {m.provider} is not on the allow list")
        problems += _spec_problems(label, m)
    return problems


def _spec_problems(label: str, m: ModelSpec) -> list[str]:
    if m.provider == "bedrock":
        return _bedrock_problems(label, m.gateway_model, m.region)
    if m.provider == "azure_openai":
        return _azure_problems(label, m.region)
    if m.provider == "vllm" and m.region not in EU_AWS_REGIONS | EU_AZURE_REGIONS:
        return [f"{label}: self-hosted region {m.region} is not an allowed EU region"]
    return []


def _base_problems(label: str, provider: str, base: str) -> list[str]:
    if base.startswith("os.environ/"):
        if _ENV_API_BASE.get(provider) != base:
            return [f"{label}: api_base from {base} is not allowed for {provider}"]
        return []  # the value is checked at gateway start (check_environment)
    host = urlparse(base).hostname or ""
    if provider == "mistral" and host == _MISTRAL_HOST:
        return []
    if provider == "azure_openai" and host.endswith(_AZURE_HOST_SUFFIXES):
        return []
    if provider == "bedrock":
        match = _BEDROCK_HOST.match(host)
        if match and match["region"] in EU_AWS_REGIONS:
            return []
    return [f"{label}: endpoint {host or base} is not an allowed EU endpoint for {provider}"]


def check_gateway_config(config: Mapping[str, Any]) -> list[str]:
    """Problems of a rendered LiteLLM config (what the gateway would actually call)."""
    problems: list[str] = []
    text = str(config).lower()
    problems += [
        f"config mentions forbidden endpoint '{w}'" for w in _FORBIDDEN_MARKERS if w in text
    ]
    for entry in config.get("model_list", []):
        params = entry.get("litellm_params", {})
        info = entry.get("model_info", {})
        provider = info.get("provider", "")
        label = f"entry {entry.get('model_name')}"
        if provider not in ALLOWED_PROVIDERS - {"fake", "ollama"}:
            problems.append(f"{label}: provider {provider!r} is not allowed in the gateway")
            continue
        if provider == "bedrock":
            region = params.get("aws_region_name")
            problems += _bedrock_problems(label, str(params.get("model", "")), region)
        elif provider == "azure_openai":
            problems += _azure_problems(label, info.get("region"))
        if provider == "mistral" and not params.get("api_base"):
            # LiteLLM would default to api.mistral.ai, which is not EU-guaranteed
            problems.append(f"{label}: Mistral needs an explicit api_base ({MISTRAL_EU_BASE})")
        if base := params.get("api_base"):
            problems += _base_problems(label, provider, str(base))
    return problems


def check_environment(env: Mapping[str, str]) -> list[str]:
    """Gateway start-up check of the endpoint variables the config refers to."""
    base = env.get("AZURE_API_BASE")
    if base:
        return _base_problems("AZURE_API_BASE", "azure_openai", base)
    return []


def assert_eu_only(problems: Iterable[str]) -> None:
    found = list(problems)
    if found:
        raise EuResidencyError("; ".join(found))
