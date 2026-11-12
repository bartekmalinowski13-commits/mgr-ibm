"""BOM Agent public API (FastAPI): ``/v1`` REST + SSE, OpenAPI 3.1 contract (ADR-0015)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api import __version__, maintenance
from bomagent_api.auth import ALGORITHMS, LocalIdp, TokenVerifier, check_algorithms
from bomagent_api.routers import api_keys, audit, identity, members, projects, runs
from bomagent_api.routers import kb as kb_routes
from bomagent_api.routers import sso as sso_routes
from bomagent_api.routers.kb import MAX_DOCUMENT
from bomagent_api.routers.projects import MAX_UPLOAD
from bomagent_api.routers.runs import MAX_REFERENCE
from bomagent_api.sso import (
    CognitoIdentityProviders,
    DnsTxtResolver,
    InMemoryIdentityProviders,
    StaticTxtResolver,
)
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.messaging import InMemoryQueue, Queue, make_queue
from bomagent_common.problems import ProblemError, problem_response
from bomagent_common.service import create_service_app
from bomagent_common.storage import InMemoryObjectStore, ObjectStore, make_object_store
from bomagent_kb import KnowledgeBase
from bomagent_llm.catalog import load_catalog
from bomagent_llm.embeddings import EmbeddingClient, GatewayEmbeddings, HashingEmbeddings

MULTIPART_OVERHEAD = 64 * 1024  # multipart boundaries and part headers


def _upload_limit(method: str, path: str) -> int | None:
    """Largest accepted body of an upload endpoint (checked before the body is read)."""
    if method != "POST":
        return None
    if path.endswith("/files"):
        return MAX_UPLOAD
    if path == "/v1/kb/documents":
        return MAX_DOCUMENT
    if path.endswith("/evaluation"):
        return MAX_REFERENCE
    return None


class Settings(ServiceSettings):
    service_name: str = "bomagent-api"
    # platform_database_url (tenant onboarding, maintenance) comes from ServiceSettings

    auth_mode: Literal["local", "oidc"] = "oidc"
    oidc_issuer: str = ""
    oidc_audience: str = "bomagent-api"
    oidc_jwks_url: str | None = None
    #: asymmetric JWS algorithms accepted from the JWKS (Cognito RS256; Supabase ES256 or
    #: RS256). HS* is refused: a shared secret is never used to verify user tokens.
    oidc_algorithms: list[str] = Field(default_factory=lambda: list(ALGORITHMS))
    #: claims as dotted paths (Supabase: ``user_metadata.email_verified``,
    #: ``["user_metadata.full_name", "user_metadata.name"]``); the first non-empty name wins
    oidc_email_claim: str = "email"
    oidc_email_verified_claim: str = "email_verified"
    oidc_name_claims: list[str] = Field(default_factory=lambda: ["name"])

    @field_validator("oidc_algorithms")
    @classmethod
    def _asymmetric_only(cls, value: list[str]) -> list[str]:
        return check_algorithms(value)

    #: SSO federation (Cognito): pool + SPA client to enable providers on, hosted domain
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_domain: str | None = None
    files_bucket: str = "bomagent-local-files"
    ingest_queue_url: str | None = None
    runs_queue_url: str | None = None
    kb_queue_url: str | None = None
    llm_gateway_url: str | None = None
    llm_gateway_key: str | None = None
    embedding_model: str = "fake-embedding"
    cors_origins: list[str] = Field(default_factory=list)
    maintenance_interval_s: float = 30.0  # outbox relay + stuck-run reaper; 0 disables
    run_timeout_s: float = 3600.0
    sse_interval_s: float = 1.0
    sse_timeout_s: float = 900.0


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    platform_engine: AsyncEngine | None = None,
    store: ObjectStore | None = None,
    queues: dict[str, Queue] | None = None,
    kb: KnowledgeBase | None = None,
    readiness: Mapping[str, ReadinessCheck] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    local = settings.environment in {"local", "test"}
    if settings.auth_mode == "local" and not local:
        raise RuntimeError("the local mock IdP is allowed only in local/test environments")
    if (
        settings.auth_mode == "oidc"
        and not local
        and not (settings.oidc_issuer and settings.oidc_jwks_url)
    ):
        raise RuntimeError("BOMAGENT_OIDC_ISSUER and BOMAGENT_OIDC_JWKS_URL are required")
    if engine is None and settings.database_url:
        engine = make_engine(settings.database_url)
    if platform_engine is None and settings.platform_database_url:
        platform_engine = make_engine(settings.platform_database_url, pool_size=2)

    checks: dict[str, ReadinessCheck] = dict(readiness or {})
    if engine is not None:
        db = engine

        async def database() -> bool:
            return await ping(db)

        checks["database"] = database

    app = create_service_app(
        settings,
        version=__version__,
        title="BOM Agent API",
        readiness=checks,
        docs=True,
        lifespan=maintenance.lifespan(settings.maintenance_interval_s, settings.run_timeout_s),
    )
    app.state.engine = engine
    app.state.platform_engine = platform_engine
    app.state.store = store or (
        make_object_store(settings, settings.files_bucket)
        if not local or settings.aws_endpoint_url or settings.s3_endpoint_url
        else InMemoryObjectStore()
    )
    if queues is None:
        if settings.queue_backend == "postgres" and engine is None:
            raise RuntimeError("the postgres queue backend needs BOMAGENT_DATABASE_URL")
        queues = {
            name: make_queue(settings, name, sqs_url=url, producer_engine=engine) or InMemoryQueue()
            for name, url in (
                ("ingest", settings.ingest_queue_url),
                ("runs", settings.runs_queue_url),
                ("kb", settings.kb_queue_url),
            )
        }
    app.state.queues = queues
    embedder: EmbeddingClient = (
        GatewayEmbeddings(
            settings.llm_gateway_url, settings.llm_gateway_key, settings.embedding_model
        )
        if settings.llm_gateway_url and settings.llm_gateway_key
        else HashingEmbeddings()
    )
    app.state.kb = kb or KnowledgeBase(embedder)
    app.state.catalog = load_catalog()
    app.state.allow_local_models = local
    if settings.cognito_user_pool_id and settings.cognito_client_id and not local:
        app.state.identity_providers = CognitoIdentityProviders(
            settings.cognito_user_pool_id, settings.cognito_client_id, settings.aws_region
        )
        app.state.txt_resolver = DnsTxtResolver()
    else:
        app.state.identity_providers = InMemoryIdentityProviders()
        app.state.txt_resolver = StaticTxtResolver()
    app.state.cognito_domain = settings.cognito_domain
    app.state.cognito_user_pool_id = settings.cognito_user_pool_id
    app.state.sse_interval_s = settings.sse_interval_s
    app.state.sse_timeout_s = settings.sse_timeout_s
    if settings.auth_mode == "local":
        idp = LocalIdp(settings.oidc_audience)
        app.state.local_idp = idp
        app.state.verifier = idp.verifier
    else:
        app.state.verifier = TokenVerifier.from_settings(settings)

    for router in (
        identity.router,
        members.router,
        api_keys.router,
        projects.router,
        runs.router,
        runs.models_router,
        audit.router,
        kb_routes.router,
        sso_routes.router,
        sso_routes.public,
    ):
        app.include_router(router)

    _install_guards(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Org-Id", "Idempotency-Key"],
        )
    return app


def _install_guards(app: FastAPI) -> None:
    """URL/upload guards and security headers on every response."""

    @app.middleware("http")
    async def upload_size_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Reject NUL bytes in the URL (PostgreSQL text cannot store them) and oversized
        uploads before the multipart body is spooled to disk."""
        raw = request.scope.get("raw_path", b"") + b"?" + request.scope.get("query_string", b"")
        if b"%00" in raw.lower() or b"\x00" in raw or "\x00" in request.url.path:
            err = ProblemError(400, "Bad Request", "NUL characters are not allowed in the URL")
            return problem_response(err.problem, request)
        limit = _upload_limit(request.method, request.url.path)
        if limit is not None:
            length = request.headers.get("content-length", "")
            if not (length.isascii() and length.isdigit()):
                err = ProblemError(411, "Length Required", "Content-Length is required")
                return problem_response(err.problem, request)
            if int(length) > limit + MULTIPART_OVERHEAD:
                err = ProblemError(
                    413, "Payload Too Large", "the upload is too large", slug="file-too-large"
                )
                return problem_response(err.problem, request)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


def openapi_document() -> dict[str, Any]:
    return create_app(Settings(environment="test", auth_mode="local")).openapi()
