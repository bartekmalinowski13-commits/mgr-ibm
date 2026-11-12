"""Service configuration loaded from environment variables (12-factor).

Secrets are never given defaults: in the cloud they come from AWS Secrets Manager
(injected by ECS as environment variables), locally from an untracked ``.env``.
"""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "dev", "staging", "prod"]
QueueBackend = Literal["sqs", "postgres"]
PLATFORM_ROLE = "bomagent_platform"


class ServiceSettings(BaseSettings):
    """Settings shared by every deployable service."""

    model_config = SettingsConfigDict(env_prefix="BOMAGENT_", env_file=None, extra="ignore")

    service_name: str = "bomagent"
    environment: Environment = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # Application role connection (no BYPASSRLS). Example:
    # postgresql+psycopg://bomagent_app:***@localhost:5432/bomagent
    database_url: str | None = Field(default=None, repr=False)  # may carry a password
    # ...or its parts (ECS: host from the stack, password injected from Secrets Manager)
    database_host: str | None = None
    database_port: int = 5432
    database_name: str = "bomagent"
    database_user: str = "bomagent_app"
    database_password: str | None = Field(default=None, repr=False)
    # CA bundle (RDS global bundle in the images). When set, connections built from the parts
    # use ``sslmode=verify-full`` against it; unset (local/test) keeps ``sslmode=require``.
    db_ssl_root_cert: str | None = None
    # Platform role (no BYPASSRLS): tenant onboarding, global KB, consuming the PostgreSQL
    # queue. Same cluster and database as the app role; composed like ``database_url``.
    platform_database_url: str | None = Field(default=None, repr=False)
    platform_database_password: str | None = Field(default=None, repr=False)

    # Message transport: ``sqs`` (AWS, default) or ``postgres`` (``app.queue_messages``,
    # the Supabase pilot deployment without SQS; consumers need the platform role).
    queue_backend: QueueBackend = "sqs"
    queue_poll_interval_s: float = 1.0  # postgres backend: re-query interval while waiting

    # OpenTelemetry: OTLP/HTTP endpoint of the collector, e.g. http://otel-lgtm:4318
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_console_exporter: bool = False

    # AWS-compatible endpoints (moto locally, real AWS in the cloud: leave None)
    aws_region: str = "eu-central-1"
    aws_endpoint_url: str | None = None

    @model_validator(mode="after")
    def _compose_database_url(self) -> Self:
        if self.database_url is None and self.database_host and self.database_password:
            self.database_url = postgres_url(
                self.database_user,
                self.database_password,
                self.database_host,
                self.database_port,
                self.database_name,
                ssl_root_cert=self.db_ssl_root_cert,
            )
        if (
            self.platform_database_url is None
            and self.database_host
            and self.platform_database_password
        ):
            self.platform_database_url = postgres_url(
                PLATFORM_ROLE,
                self.platform_database_password,
                self.database_host,
                self.database_port,
                self.database_name,
                ssl_root_cert=self.db_ssl_root_cert,
            )
        return self

    @property
    def is_production_like(self) -> bool:
        return self.environment in {"staging", "prod"}


def postgres_url(
    user: str,
    password: str,
    host: str,
    port: int,
    database: str,
    *,
    ssl_root_cert: str | None = None,
) -> str:
    """psycopg URL with TLS required (Aurora enforces ``rds.force_ssl``).

    With ``ssl_root_cert`` the server certificate and host name are verified against that
    CA bundle (``sslmode=verify-full``) instead of only encrypting the channel.
    """
    tls = (
        f"sslmode=verify-full&sslrootcert={quote(ssl_root_cert, safe='/')}"
        if ssl_root_cert
        else "sslmode=require"
    )
    return (
        f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}?{tls}"
    )
