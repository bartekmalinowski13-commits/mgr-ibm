"""One process for the Supabase pilot: the API, the three workers and the built SPA.

* **API** - ``bomagent_api.create_app`` unchanged (routes, auth, outbox relay and the
  stuck-run reaper in its maintenance loop); Supabase Auth tokens via the ``oidc_*``
  settings, whose defaults here are Supabase's.
* **Workers** - ingest, agent and KB indexer handlers consume ``PostgresQueue``s
  (``app.queue_messages``) with the platform role; every handler runs in the message's
  tenant context with the app role (RLS), exactly as the separate AWS services do. Design
  files are parsed in the resource-limited sandbox (``bomagent_cad.sandbox``, used by the
  handlers).
* **SPA** - files from ``static_dir``; any other non-API GET path falls back to
  ``index.html``; ``/config.json`` tells the SPA how to sign in (the Supabase anon key is
  public by design - RLS of *our* database never trusts it, the API verifies the user JWT).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_agent_worker.handler import RunWorker
from bomagent_agents.fake_responder import heuristic_responder
from bomagent_agents.retrieval import Retriever
from bomagent_api.app import Settings as ApiSettings
from bomagent_api.app import create_app as create_api
from bomagent_api.app import require_https
from bomagent_common.config import QueueBackend
from bomagent_common.db import make_engine
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Handler, PostgresQueue, Queue, consume_forever, make_queue
from bomagent_common.problems import ProblemError, problem_response
from bomagent_common.storage import InMemoryObjectStore, ObjectStore, make_object_store
from bomagent_ingest.handler import IngestWorker
from bomagent_kb import KnowledgeBase
from bomagent_kb_indexer.handler import KbIndexer
from bomagent_llm.chat import ChatClient, FakeChat, GatewayChat
from bomagent_llm.embeddings import EmbeddingClient, GatewayEmbeddings, HashingEmbeddings

log = get_logger(__name__)
QUEUES = ("ingest", "runs", "kb")
SUPABASE_ALGORITHMS = ["ES256", "RS256"]
SUPABASE_NAME_CLAIMS = ["user_metadata.full_name", "user_metadata.name"]
IMMUTABLE = "public, max-age=31536000, immutable"
RetrieverFactory = Callable[[uuid.UUID, str | None], Retriever]


SOCIAL_PROVIDERS = ("google", "azure", "apple")  # Supabase ids; Microsoft is "azure"


class Settings(ApiSettings):
    """API settings plus the pilot's: Supabase defaults, SPA, in-process workers."""

    service_name: str = "bomagent-allinone"
    queue_backend: QueueBackend = "postgres"
    oidc_audience: str = "authenticated"
    oidc_algorithms: list[str] = Field(default_factory=lambda: list(SUPABASE_ALGORITHMS))
    oidc_email_verified_claim: str = "user_metadata.email_verified"
    oidc_name_claims: list[str] = Field(default_factory=lambda: list(SUPABASE_NAME_CLAIMS))
    #: ``https://<ref>.supabase.co``: issuer and JWKS default to its ``/auth/v1``
    supabase_url: str | None = None
    #: the project's anon (publishable) key - public by design, handed to the SPA
    supabase_anon_key: str | None = None
    #: built SPA (``apps/web/dist``); unset = API only
    static_dir: str | None = None
    #: comma-separated Supabase social providers shown on the sign-in page (``google``,
    #: ``azure`` = Microsoft, ``apple``); empty = e-mail + password only
    social_providers: str = ""
    start_workers: bool = True
    queue_wait_seconds: int = 5
    db_pool_size: int = 5  # app role; the platform role uses 2 (mind the pooler's limits)
    dead_letter_retention_s: float = 14 * 24 * 3600.0
    use_docling: bool = False
    #: allow the deterministic fake LLM provider when no gateway is configured. ``None``
    #: (default) = allowed only in local/test; the pilot sets it explicitly while it still
    #: runs without a gateway (``BOMAGENT_ALLOW_FAKE_LLM``)
    allow_fake_llm: bool | None = None

    @property
    def social_provider_ids(self) -> list[str]:
        """Known provider ids from ``social_providers``: lower-case, deduplicated, in order."""
        out: list[str] = []
        for raw in self.social_providers.split(","):
            provider = raw.strip().lower()
            if provider in SOCIAL_PROVIDERS and provider not in out:
                out.append(provider)
        return out

    @model_validator(mode="after")
    def _supabase_defaults(self) -> Self:
        if self.queue_backend != "postgres":
            raise ValueError("the all-in-one process supports only the postgres queue backend")
        if self.supabase_url:
            self.supabase_url = self.supabase_url.rstrip("/")
            self.oidc_issuer = self.oidc_issuer or f"{self.supabase_url}/auth/v1"
            self.oidc_jwks_url = (
                self.oidc_jwks_url or f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
            )
            # user_metadata is user-editable: ask Supabase Auth whether the e-mail is
            # confirmed where it matters (organisation creation, invitations)
            self.oidc_userinfo_url = self.oidc_userinfo_url or f"{self.supabase_url}/auth/v1/user"
            self.oidc_userinfo_apikey = self.oidc_userinfo_apikey or self.supabase_anon_key
        local = self.environment in ("local", "test")
        if self.allow_fake_llm is None:
            self.allow_fake_llm = local  # fail closed outside local/test (see ``_llm``)
        if not local:
            # Supabase is reached over the internet; so is the gateway unless it is another
            # Fly app of the same organisation on the private 6PN network (``*.internal``)
            require_https(self, (*self._HTTPS_ONLY, "supabase_url"))
            if not _is_private_network_url(self.llm_gateway_url):
                require_https(self, ("llm_gateway_url",))
        return self


def _is_private_network_url(url: str | None) -> bool:
    """``http(s)://<app>.internal[:port]``: Fly's private 6PN DNS (WireGuard, same org)."""
    if not url:
        return False
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return parsed.scheme in ("http", "https") and host.endswith(".internal") and len(host) > 9


def spa_csp(supabase_url: str | None) -> str:
    """CSP for the SPA: own origin only; the browser talks to Supabase Auth directly."""
    connect = " ".join(["'self'", *([supabase_url.rstrip("/")] if supabase_url else [])])
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; "
        f"connect-src {connect}; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'"
    )


def _llm(settings: Settings) -> tuple[ChatClient, EmbeddingClient]:
    """The EU LLM gateway when configured; the fake provider only when explicitly allowed."""
    url, key = settings.llm_gateway_url, settings.llm_gateway_key
    if bool(url) != bool(key):
        raise RuntimeError(
            "BOMAGENT_LLM_GATEWAY_URL and BOMAGENT_LLM_GATEWAY_KEY must be set both or not at all"
        )
    if url and key:
        return (
            GatewayChat(url, key),
            GatewayEmbeddings(url, key, settings.embedding_model),
        )
    if not settings.allow_fake_llm:
        raise RuntimeError(
            "no LLM gateway configured: set BOMAGENT_LLM_GATEWAY_URL and BOMAGENT_LLM_GATEWAY_KEY"
            " (EU gateway, ADR-0006) or, for a demo without real models,"
            " BOMAGENT_ALLOW_FAKE_LLM=true"
        )
    log.warning("llm_fake_provider", reason="BOMAGENT_ALLOW_FAKE_LLM and no gateway configured")
    return FakeChat(heuristic_responder), HashingEmbeddings()


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    platform_engine: AsyncEngine | None = None,
    store: ObjectStore | None = None,
    chat: ChatClient | None = None,
    kb: KnowledgeBase | None = None,
    retriever_factory: RetrieverFactory | None = None,
) -> FastAPI:
    settings = settings or Settings()
    local = settings.environment in {"local", "test"}
    if engine is None and settings.database_url:
        engine = make_engine(settings.database_url, pool_size=settings.db_pool_size)
    if platform_engine is None and settings.platform_database_url:
        platform_engine = make_engine(settings.platform_database_url, pool_size=2)
    if engine is None or platform_engine is None:
        raise RuntimeError(
            "BOMAGENT_DATABASE_URL (app role) and BOMAGENT_PLATFORM_DATABASE_URL (platform"
            " role) are required (or their _PASSWORD + BOMAGENT_DATABASE_HOST)"
        )
    if store is None:
        store = (
            make_object_store(settings, settings.files_bucket)
            if not local or settings.s3_endpoint_url or settings.aws_endpoint_url
            else InMemoryObjectStore()
        )
    default_chat, embedder = _llm(settings)
    kb = kb or KnowledgeBase(embedder)
    queues: dict[str, Queue] = {}
    for name in QUEUES:
        queue = make_queue(
            settings, name, sqs_url=None, producer_engine=engine, consumer_engine=platform_engine
        )
        assert queue is not None  # postgres backend (validated in Settings)
        queues[name] = queue
    handlers: dict[str, Handler] = {
        "ingest": IngestWorker(engine, store).handle,
        "runs": RunWorker(
            engine=engine,
            store=store,
            chat=chat or default_chat,
            kb=kb,
            retriever_factory=retriever_factory,
            allow_unregistered=local,
        ).handle,
        "kb": KbIndexer(
            kb=kb,
            app_engine=engine,
            tenant_store=store,
            platform_engine=platform_engine,
            use_docling=settings.use_docling,
        ).handle,
    }
    workers = _Workers(settings, queues, handlers)
    readiness = {"workers": workers.alive} if settings.start_workers else {}
    app = create_api(
        settings,
        engine=engine,
        platform_engine=platform_engine,
        store=store,
        queues=queues,
        kb=kb,
        readiness=readiness,
    )
    app.state.workers = workers
    fake = isinstance(default_chat, FakeChat)
    app.state.readyz_info = {"llm": "fake" if fake else "gateway"}  # shown by /readyz
    if fake:
        # every run is answered by the fake provider anyway, so its catalogue entries
        # (``fake-closed``, the default model; residency ``local``) must be selectable
        # outside local/test; with the gateway the API's rule (no local models) applies
        app.state.allow_local_models = True
    _wrap_lifespan(app, workers)
    _install_frontend(app, settings)
    return app


class _Workers:
    """The three queue consumers and the dead-letter purge, as asyncio tasks."""

    def __init__(
        self, settings: Settings, queues: dict[str, Queue], handlers: dict[str, Handler]
    ) -> None:
        self._settings = settings
        self._queues = queues
        self._handlers = handlers
        self._stop = asyncio.Event()
        self.tasks: list[asyncio.Task[None]] = []

    async def alive(self) -> bool:
        return bool(self.tasks) and not any(t.done() for t in self.tasks)

    def start(self) -> None:
        self._stop.clear()
        for name, queue in self._queues.items():
            self.tasks.append(
                asyncio.create_task(
                    consume_forever(
                        queue,
                        self._handlers[name],
                        stop=self._stop,
                        wait_seconds=self._settings.queue_wait_seconds,
                        max_messages=1,  # slow handlers: see consume_forever
                    ),
                    name=f"consumer-{name}",
                )
            )
            log.info("consumer_started", queue=name, backend="postgres")
        self.tasks.append(asyncio.create_task(self._purge_loop(), name="dead-letter-purge"))

    async def _purge_loop(self) -> None:
        while not self._stop.is_set():
            for queue in self._queues.values():
                if isinstance(queue, PostgresQueue):
                    try:
                        await queue.purge_dead(older_than_s=self._settings.dead_letter_retention_s)
                    except Exception:
                        log.exception("dead_letter_purge_failed", queue=queue.name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=3600)

    async def stop(self, grace_s: float = 30.0) -> None:
        """Let running handlers finish (the queues are long-polled, so consumers notice
        within ``queue_wait_seconds``); cancel what is still running after ``grace_s`` -
        its message is redelivered after the visibility timeout."""
        self._stop.set()
        if not self.tasks:
            return
        _, pending = await asyncio.wait(self.tasks, timeout=grace_s)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()


def _wrap_lifespan(app: FastAPI, workers: _Workers) -> None:
    api_lifespan = app.router.lifespan_context
    start = workers._settings.start_workers

    @contextlib.asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[Any]:
        async with api_lifespan(a) as state:
            if start:
                workers.start()
            try:
                yield state
            finally:
                await workers.stop()

    app.router.lifespan_context = lifespan


def _install_frontend(app: FastAPI, settings: Settings) -> None:
    @app.get("/config.json", include_in_schema=False)
    async def config_json() -> Response:
        if settings.auth_mode == "local":
            return JSONResponse({"auth": {"mode": "local"}})
        if not (settings.supabase_url and settings.supabase_anon_key):
            raise ProblemError(404, "Not Found", "no sign-in configuration")
        auth: dict[str, Any] = {
            "mode": "supabase",
            "url": settings.supabase_url,
            "anonKey": settings.supabase_anon_key,
        }
        if settings.social_provider_ids:
            auth["providers"] = settings.social_provider_ids
        return JSONResponse({"auth": auth})

    if not settings.static_dir:
        return
    root = Path(settings.static_dir).resolve()
    index = root / "index.html"
    csp = spa_csp(settings.supabase_url)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(request: Request, path: str) -> Response:
        if path == "v1" or path.startswith("v1/"):
            err = ProblemError(404, "Not Found", "no such endpoint")
            return problem_response(err.problem, request)
        headers = {"Content-Security-Policy": csp}
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                cache = IMMUTABLE if candidate.parent.name == "assets" else "no-cache"
                return FileResponse(candidate, headers=headers | {"Cache-Control": cache})
            if "." in path.rsplit("/", 1)[-1]:  # a missing file, not a client-side route
                err = ProblemError(404, "Not Found", "no such file")
                return problem_response(err.problem, request)
        return FileResponse(index, headers=headers | {"Cache-Control": "no-cache"})
