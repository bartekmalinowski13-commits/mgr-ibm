from __future__ import annotations

from fastapi import FastAPI

from bomagent_api import __version__
from bomagent_api.auth import Authenticator, DevAuthenticator, OidcAuthenticator
from bomagent_api.routes import ApiServices, router
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.service import create_service_app


class Settings(ServiceSettings):
    service_name: str = "bomagent-api"
    files_bucket: str = "bomagent-local-files"
    ingest_queue_url: str | None = None
    runs_queue_url: str | None = None
    # authentication: "oidc" (default, any OIDC provider; Cognito in AWS) or "dev" (local only)
    auth_mode: str = "oidc"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_tenant_claim: str = "org_id"
    oidc_roles_claim: str = "roles"
    dev_auth_secret: str | None = None
    allow_local_models: bool = False


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_mode == "dev":
        if settings.is_production_like:
            raise RuntimeError("dev authentication is not allowed in staging/prod")
        if not settings.dev_auth_secret or len(settings.dev_auth_secret) < 32:
            raise RuntimeError("BOMAGENT_DEV_AUTH_SECRET (>= 32 chars) is required for dev auth")
        return DevAuthenticator(settings.dev_auth_secret)
    if not (settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url):
        raise RuntimeError("OIDC issuer, audience and JWKS URL are required")
    return OidcAuthenticator(
        settings.oidc_issuer,
        settings.oidc_audience,
        settings.oidc_jwks_url,
        tenant_claim=settings.oidc_tenant_claim,
        roles_claim=settings.oidc_roles_claim,
    )


def build_services(settings: Settings) -> ApiServices:
    from bomagent_common.messaging import SqsQueue
    from bomagent_common.storage import S3ObjectStore
    from bomagent_llm.catalog import load_catalog

    if not (settings.database_url and settings.ingest_queue_url and settings.runs_queue_url):
        raise RuntimeError("database URL and both queue URLs are required")
    if settings.allow_local_models and settings.is_production_like:
        raise RuntimeError("local models are not allowed in staging/prod")
    return ApiServices(
        engine=make_engine(settings.database_url),
        store=S3ObjectStore(
            settings.files_bucket,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ),
        ingest_queue=SqsQueue(
            settings.ingest_queue_url,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ),
        runs_queue=SqsQueue(
            settings.runs_queue_url,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        ),
        authenticator=build_authenticator(settings),
        catalog=load_catalog(),
        allow_local_models=settings.allow_local_models,
    )


def create_app(settings: Settings | None = None, services: ApiServices | None = None) -> FastAPI:
    settings = settings or Settings()
    readiness: dict[str, ReadinessCheck] = {}
    if services is None and settings.database_url and settings.runs_queue_url:
        services = build_services(settings)
    if services is not None:
        engine = services.engine

        async def database() -> bool:
            return await ping(engine)

        readiness["database"] = database
    elif settings.database_url:
        engine = make_engine(settings.database_url, pool_size=2)

        async def database() -> bool:
            return await ping(engine)

        readiness["database"] = database
    app = create_service_app(
        settings,
        version=__version__,
        title="BOM Agent API",
        readiness=readiness,
        docs=True,
    )
    if services is not None:
        app.state.services = services
        app.include_router(router)
    return app
