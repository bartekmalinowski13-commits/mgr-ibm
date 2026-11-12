"""Model catalogue loader (closed vs open-weight, EU residency)."""

from __future__ import annotations

import os
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ALLOWED_RESIDENCY = frozenset({"eu-region", "eu-geo", "local"})


class LicenseClass(StrEnum):
    CLOSED = "closed"
    OPEN_WEIGHT = "open-weight"


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    gateway_model: str
    provider: str
    license_class: LicenseClass
    residency: Literal["eu-region", "eu-geo", "local"]
    region: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    tier: Literal["fast", "balanced", "strong"] | None = None
    dimensions: int | None = None
    cost_in_eur: float = 0.0  # per 1M input tokens
    cost_out_eur: float = 0.0  # per 1M output tokens
    enabled: bool = False
    verified: bool = False
    notes: str = ""

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            (input_tokens * self.cost_in_eur + output_tokens * self.cost_out_eur) / 1_000_000, 6
        )


class ModelNotAllowedError(LookupError):
    """Unknown, disabled, unverified or non-EU model."""


class Catalog(BaseModel):
    models: list[ModelSpec]

    def get(self, model_id: str, *, allow_local: bool = True) -> ModelSpec:
        spec = next((m for m in self.models if m.id == model_id), None)
        if spec is None:
            raise ModelNotAllowedError(f"model {model_id!r} is not in the catalogue")
        if not spec.enabled or not spec.verified:
            raise ModelNotAllowedError(
                f"model {model_id!r} is disabled or its regional availability is unverified"
            )
        if spec.residency not in ALLOWED_RESIDENCY:  # pragma: no cover - schema forbids
            raise ModelNotAllowedError(f"model {model_id!r} is not processed in the EU")
        if spec.residency == "local" and not allow_local:
            raise ModelNotAllowedError(f"model {model_id!r} is for local development only")
        return spec

    def enabled(self, capability: str | None = None) -> list[ModelSpec]:
        return [
            m
            for m in self.models
            if m.enabled and m.verified and (capability is None or capability in m.capabilities)
        ]


OVERRIDE_ENV = "BOMAGENT_CATALOG_OVERRIDE"


def _apply_override(catalog: Catalog, override: str | Path) -> Catalog:
    """Local development override: ``enable: [<id>, ...]`` switches on **local** entries only.

    Hosted (EU cloud) entries can never be enabled this way - flipping them is a reviewed
    change of ``models.yaml`` after checking availability in the provider account.
    """
    data = yaml.safe_load(Path(override).read_text(encoding="utf-8")) or {}
    ids = [str(i) for i in data.get("enable", [])]
    by_id = {m.id: m for m in catalog.models}
    for model_id in ids:
        spec = by_id.get(model_id)
        if spec is None:
            raise ValueError(f"catalogue override: unknown model {model_id!r}")
        if spec.residency != "local":
            raise ValueError(
                f"catalogue override: {model_id!r} is not a local model; hosted models are "
                "enabled in models.yaml only"
            )
    models = [
        m.model_copy(update={"enabled": True, "verified": True}) if m.id in ids else m
        for m in catalog.models
    ]
    return Catalog(models=models)


def load_catalog(path: str | Path | None = None, *, override: str | Path | None = None) -> Catalog:
    text = (
        Path(path).read_text(encoding="utf-8")
        if path is not None
        else resources.files(__package__).joinpath("models.yaml").read_text(encoding="utf-8")
    )
    catalog = Catalog.model_validate(yaml.safe_load(text))
    override = override or os.environ.get(OVERRIDE_ENV)
    return _apply_override(catalog, override) if override else catalog
