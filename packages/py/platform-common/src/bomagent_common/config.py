"""Service configuration loaded from environment variables (12-factor).

Secrets are never given defaults: in the cloud they come from AWS Secrets Manager
(injected by ECS as environment variables), locally from an untracked ``.env``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "staging", "prod"]


class ServiceSettings(BaseSettings):
    """Settings shared by every deployable service."""

    model_config = SettingsConfigDict(env_prefix="BOMAGENT_", env_file=None, extra="ignore")

    service_name: str = "bomagent"
    environment: Environment = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # Application role connection (no BYPASSRLS). Example:
    # postgresql+psycopg://bomagent_app:***@localhost:5432/bomagent
    database_url: str | None = None

    # OpenTelemetry: OTLP/HTTP endpoint of the collector, e.g. http://otel-lgtm:4318
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_console_exporter: bool = False

    # AWS-compatible endpoints (moto locally, real AWS in the cloud: leave None)
    aws_region: str = "eu-central-1"
    aws_endpoint_url: str | None = None

    @property
    def is_production_like(self) -> bool:
        return self.environment in {"staging", "prod"}
