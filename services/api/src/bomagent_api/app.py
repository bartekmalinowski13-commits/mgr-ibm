"""BOM Agent public API (FastAPI): ``/v1`` REST + SSE, OpenAPI 3.1 contract (ADR-0015)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar, Literal, Self

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api import __version__, maintenance
from bomagent_api.auth import ALGORITHMS, LocalIdp, TokenVerifier, UserInfo, check_algorithms
from bomagent_api.authz import MfaRequiredError, mfa_required_handler
from bomagent_api.ip_limits import install_ip_limits, install_origin
from bomagent_api.routers import (
    api_keys,
    audit,
    exports,
    identity,
    members,
    projects,
    runs,
    samples,
)
from bomagent_api.routers import kb as kb_routes
from bomagent_api.routers import sso as sso_routes
from bomagent_api.routers.kb import MAX_DOCUMENT
from bomagent_api.routers.projects import MAX_UPLOAD
from bomagent_api.routers.runs import MAX_REFERENCE
from bomagent_api.sso import (
    CognitoIdentityProviders,
    Connection,
    DnsTxtResolver,
    InMemoryIdentityProviders,
    StaticTxtResolver,
)
from bomagent_common.audit_anchor import AnchorSink, FileAnchorSink, S3AnchorSink
from bomagent_common.config import ServiceSettings
from bomagent_common.db import make_engine, ping
from bomagent_common.health import ReadinessCheck
from bomagent_common.logging import get_logger
from bomagent_common.mailer import Mailer, mailer_from_settings
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


def require_https(settings: object, fields: tuple[str, ...]) -> None:
    for name in fields:
        value = getattr(settings, name, None)
        if value and not str(value).startswith("https://"):
            raise ValueError(f"{name} must use https:// outside local/test")


log = get_logger(__name__)


class Settings(ServiceSettings):
    service_name: str = "bomagent-api"
    # platform_database_url (tenant onboarding, maintenance) comes from ServiceSettings

    auth_mode: Literal["local", "oidc"] = "oidc"
    #: per-IP limits before the organisation context (SEC-03). Default: on outside local/test
    #: when ``client_ip_header`` is set; without it the socket peer is a shared proxy address and
    #: every user would share one bucket, so the limits stay off.
    ip_rate_limit: bool | None = None
    #: daily audit-chain anchors (ADR-0011): a directory (write-once volume / off-platform copy)
    #: or an S3 bucket with Object Lock; both unset = no export
    audit_anchor_dir: str | None = None
    audit_anchor_bucket: str | None = None
    audit_anchor_endpoint_url: str | None = None  # S3-compatible stores (Supabase Storage)
    #: edge header that carries the client address (``Fly-Client-IP``,
    #: ``CloudFront-Viewer-Address``); never X-Forwarded-For. Unset = socket peer.
    client_ip_header: str | None = None
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
    #: SEC-06 step-up MFA, OFF by default so the pilot keeps working. When on, member, API key,
    #: SSO and organisation management need a token that proves a second factor (``aal`` aal2
    #: for Supabase, or an ``amr`` value below for Cognito/OIDC); else 403 ``mfa-required``.
    #: Turn it on only after the admins have enrolled a factor (Supabase: enable TOTP MFA).
    mfa_enforced: bool = False
    #: RFC 8176 ``amr`` strings that count as multi-factor (Cognito pre-token trigger)
    oidc_mfa_amr_values: list[str] = Field(default_factory=lambda: ["mfa"])
    #: when set, a verified e-mail (org creation, invitation acceptance) is confirmed with
    #: the identity provider's user endpoint instead of a token claim (Supabase:
    #: ``<url>/auth/v1/user`` + the anon key) - for providers whose claim the user can edit
    oidc_userinfo_url: str | None = None
    oidc_userinfo_apikey: str | None = Field(default=None, repr=False)

    #: invitation e-mail (UX-02). Off unless ``smtp_host`` is set (no default host: the EU
    #: relay is the operator's choice); ``invite_base_url`` is the web origin used for the
    #: ``/invite/<token>`` link. Without it the invitation is created but nothing is sent.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_sender: str | None = None
    smtp_implicit_tls: bool = False
    invite_base_url: str | None = None

    @field_validator("oidc_algorithms")
    @classmethod
    def _asymmetric_only(cls, value: list[str]) -> list[str]:
        return check_algorithms(value)

    #: endpoints that leave the host: plain HTTP would let a network attacker swap the
    #: JWKS (forged tokens) or read data in transit. The AWS LLM gateway is excluded: it
    #: is reached inside the VPC (``http://litellm:4000``).
    _HTTPS_ONLY: ClassVar[tuple[str, ...]] = (
        "oidc_jwks_url",
        "oidc_userinfo_url",
        "s3_endpoint_url",
    )

    @model_validator(mode="after")
    def _https_outside_local(self) -> Self:
        if self.environment not in ("local", "test"):
            require_https(self, self._HTTPS_ONLY)
        return self

    #: SSO federation (Cognito): pool + SPA client to enable providers on, hosted domain
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_domain: str | None = None
    #: members of an enforced SSO domain must have signed in at the identity provider within
    #: this many seconds (``auth_time`` claim; SEC-05: removed IdP users lose access within
    #: it instead of at refresh-token expiry). 0 = off. Owners (break-glass) are exempt.
    sso_max_auth_age_s: int = Field(default=8 * 3600, ge=0)
    files_bucket: str = "bomagent-local-files"
    ingest_queue_url: str | None = None
    runs_queue_url: str | None = None
    kb_queue_url: str | None = None
    llm_gateway_url: str | None = None
    llm_gateway_key: str | None = Field(default=None, repr=False)
    #: run without a gateway on non-semantic hashing embeddings (explicit opt-in outside
    #: local/test, ARCH-07); never set this for real customer data
    allow_fake_llm: bool | None = None
    embedding_model: str = "fake-embedding"
    cors_origins: list[str] = Field(default_factory=list)
    maintenance_interval_s: float = 30.0  # outbox relay + stuck-run reaper; 0 disables
    run_timeout_s: float = 3600.0
    sse_interval_s: float = 1.0
    sse_timeout_s: float = 900.0
    #: add the ``[Sample] ...`` projects to every new organisation (and allow the owner to
    #: re-add them). Unset: on in local/test/dev, off in staging/prod until enabled explicitly.
    seed_samples: bool | None = None

    @property
    def docs_enabled(self) -> bool:
        """Swagger UI and ``/openapi.json`` only where the API is explored (SEC-11); the contract
        is published from the repository (``services/api/openapi.json``)."""
        return self.environment in {"local", "test", "dev"}

    @property
    def samples_enabled(self) -> bool:
        if self.seed_samples is not None:
            return self.seed_samples
        return self.environment in {"local", "test", "dev"}

    @property
    def ip_limits_on(self) -> bool:
        if self.ip_rate_limit is not None:
            return self.ip_rate_limit
        return self.environment not in {"local", "test"} and bool(self.client_ip_header)


def anchor_sink_for(settings: Settings) -> AnchorSink | None:
    if settings.audit_anchor_bucket and settings.audit_anchor_dir:
        log.warning("audit_anchor_config_conflict", used="bucket", ignored="dir")
    if settings.audit_anchor_endpoint_url and not settings.audit_anchor_bucket:
        log.warning("audit_anchor_endpoint_without_bucket")
    if settings.audit_anchor_bucket:
        return S3AnchorSink(
            settings.audit_anchor_bucket,
            region=settings.aws_region,
            endpoint_url=settings.audit_anchor_endpoint_url,
            s3_compatible=bool(settings.audit_anchor_endpoint_url),
        )
    if settings.audit_anchor_dir:
        return FileAnchorSink(settings.audit_anchor_dir)
    return None


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def _embedder_for(settings: Settings, *, local: bool) -> EmbeddingClient:
    """Gateway embeddings; hashing only in local/test or with an explicit opt-in (ARCH-07)."""
    if settings.llm_gateway_url and settings.llm_gateway_key:
        return GatewayEmbeddings(
            settings.llm_gateway_url, settings.llm_gateway_key, settings.embedding_model
        )
    if local or settings.allow_fake_llm:
        return HashingEmbeddings()
    raise RuntimeError(
        "BOMAGENT_LLM_GATEWAY_URL/KEY are required outside local/test"
        " (BOMAGENT_ALLOW_FAKE_LLM=true opts in to non-semantic hashing embeddings)"
    )


def _configure_mail(app: FastAPI, settings: Settings, mailer: Mailer | None) -> None:
    app.state.invite_base_url = (settings.invite_base_url or "").rstrip("/")
    app.state.mailer = mailer or mailer_from_settings(
        settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        sender=settings.smtp_sender,
        implicit_tls=settings.smtp_implicit_tls,
    )


def _install_flags(app: FastAPI, settings: Settings) -> None:
    """Per-process switches read from ``app.state`` by routers and dependencies."""
    app.state.cognito_domain = settings.cognito_domain
    app.state.cognito_user_pool_id = settings.cognito_user_pool_id
    app.state.samples_enabled = settings.samples_enabled
    app.state.sso_max_auth_age_s = settings.sso_max_auth_age_s


def _install_mfa(app: FastAPI, settings: Settings) -> None:
    """Step-up MFA (SEC-06) and the SSE timings: small per-process switches on ``app.state``."""
    app.state.sse_interval_s = settings.sse_interval_s
    app.state.sse_timeout_s = settings.sse_timeout_s
    app.state.mfa_enforced = settings.mfa_enforced
    app.add_exception_handler(MfaRequiredError, mfa_required_handler)


class UnavailableIdentityProviders:
    """Hosted deployment without an identity broker (review M-4): a connection is never
    federated, so saving one is recorded as ``status='failed'`` with this reason instead of
    being reported as active."""

    REASON = "SSO is not available on this deployment (no identity broker is configured)"

    async def apply(self, connection: Connection, client_secret: str | None) -> None:
        raise RuntimeError(self.REASON)

    async def remove(self, provider_name: str) -> None:
        return None


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    platform_engine: AsyncEngine | None = None,
    store: ObjectStore | None = None,
    queues: dict[str, Queue] | None = None,
    kb: KnowledgeBase | None = None,
    mailer: Mailer | None = None,
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
        docs=settings.docs_enabled,
        lifespan=maintenance.lifespan(
            settings.maintenance_interval_s, settings.run_timeout_s, anchor_sink_for(settings)
        ),
    )
    app.state.engine, app.state.platform_engine = engine, platform_engine
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
    embedder = _embedder_for(settings, local=local)
    app.state.kb = kb or KnowledgeBase(embedder)
    _configure_mail(app, settings, mailer)
    app.state.catalog = load_catalog()
    app.state.allow_local_models = local
    if settings.cognito_user_pool_id and settings.cognito_client_id and not local:
        app.state.identity_providers = CognitoIdentityProviders(
            settings.cognito_user_pool_id, settings.cognito_client_id, settings.aws_region
        )
        app.state.txt_resolver = DnsTxtResolver()
    elif local:
        app.state.identity_providers = InMemoryIdentityProviders()
        app.state.txt_resolver = StaticTxtResolver()
    else:  # hosted without Cognito (e.g. the Supabase pilot): nothing can be federated
        app.state.identity_providers = UnavailableIdentityProviders()
        app.state.txt_resolver = StaticTxtResolver()
    _install_flags(app, settings)
    if settings.auth_mode == "local":
        idp = LocalIdp(settings.oidc_audience)
        app.state.local_idp = idp
        app.state.verifier = idp.verifier
    else:
        app.state.verifier = TokenVerifier.from_settings(settings)
    _install_mfa(app, settings)
    app.state.userinfo = (
        UserInfo(settings.oidc_userinfo_url, settings.oidc_userinfo_apikey)
        if settings.oidc_userinfo_url
        else None
    )

    for router in (
        identity.router,
        members.router,
        api_keys.router,
        projects.router,
        samples.router,
        runs.router,
        runs.models_router,
        audit.router,
        exports.router,
        kb_routes.router,
        sso_routes.router,
        sso_routes.public,
    ):
        app.include_router(router)

    _install_guards(app, settings)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Org-Id", "Idempotency-Key"],
        )
    return app


def _install_guards(app: FastAPI, settings: Settings) -> None:
    """URL/upload guards, per-IP limits and security headers on every response."""
    install_origin(app, header=settings.client_ip_header)
    install_ip_limits(app, enabled=settings.ip_limits_on, header=settings.client_ip_header)
    if not settings.client_ip_header and settings.environment not in {"local", "test"}:
        # behind a proxy the socket peer is the proxy: the per-IP limits stay off and audit
        # events record the proxy's address
        log.warning(
            "client_ip_header_unset",
            limits="off",
            audit_source_ip="socket peer",
            fix="set BOMAGENT_CLIENT_IP_HEADER to the trusted edge header",
        )

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
