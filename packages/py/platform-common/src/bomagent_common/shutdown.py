"""Graceful process shutdown for every service container.

On SIGTERM uvicorn stops accepting connections, then waits for the open ones to close and only
then runs the lifespan shutdown. A long-lived response (the runs' Server-Sent Events, up to 15
minutes) would hold that wait until the host SIGKILLs the process, and lifespan teardown -
stopping the queue consumers, releasing their messages - would never run.

* ``ShutdownSignal`` (``app.state.shutdown``) is requested from the signal handler itself, so
  long-lived responses end at once (``await signal.sleep(interval)`` returns ``True``) and
  registered callbacks run (the queue consumers stop claiming new messages).
* ``GracefulServer`` requests it in ``handle_exit``; ``server_config`` bounds the wait for open
  connections (``BOMAGENT_SHUTDOWN_GRACE_S``, default 15 s) as a backstop.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from types import FrameType
from typing import Any

import uvicorn
from fastapi import FastAPI

from bomagent_common.logging import get_logger

log = get_logger(__name__)

#: how long uvicorn waits for open connections after SIGTERM before it closes them; the
#: consumers' own grace (30 s) follows, both inside Fly's ``kill_timeout`` of 60 s
DEFAULT_GRACE_S = 15
ENV_GRACE_S = "BOMAGENT_SHUTDOWN_GRACE_S"


class ShutdownSignal:
    """A shutdown request that is safe to raise from a signal handler or another thread."""

    def __init__(self) -> None:
        self._requested = False
        self._event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._callbacks: list[Callable[[], None]] = []

    @property
    def requested(self) -> bool:
        return self._requested

    def on_request(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` on the event loop once shutdown is requested."""
        self._callbacks.append(callback)

    def _bind(self) -> asyncio.Event:
        if self._event is None:
            self._loop = asyncio.get_running_loop()
            self._event = asyncio.Event()
            if self._requested:
                self._event.set()
        return self._event

    async def sleep(self, seconds: float) -> bool:
        """Sleep up to ``seconds``; ``True`` as soon as shutdown is requested."""
        event = self._bind()
        if event.is_set():
            return True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=max(seconds, 0))
        return event.is_set()

    def _fire(self) -> None:
        if self._event is not None:
            self._event.set()
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback()
            except Exception:
                log.exception("shutdown_callback_failed")

    def request(self) -> None:
        if self._requested:
            return
        self._requested = True
        loop = self._loop
        if loop is None:
            with contextlib.suppress(RuntimeError):
                loop = asyncio.get_running_loop()
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._fire)
        else:
            self._fire()


def shutdown_of(app: FastAPI) -> ShutdownSignal:
    signal: ShutdownSignal | None = getattr(app.state, "shutdown", None)
    if signal is None:
        signal = ShutdownSignal()
        app.state.shutdown = signal
    return signal


def _unwrap(app: Any) -> FastAPI | None:
    """The FastAPI app under uvicorn's middleware wrappers (each keeps the next in ``.app``)."""
    for _ in range(16):
        if isinstance(app, FastAPI):
            return app
        app = getattr(app, "app", None)
        if app is None:
            return None
    return None


class GracefulServer(uvicorn.Server):
    """uvicorn server whose SIGTERM/SIGINT handler also requests the app's shutdown."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        super().handle_exit(sig, frame)
        app = _unwrap(getattr(self.config, "loaded_app", None))
        if app is not None:
            log.info("shutdown_requested", signal=sig)
            shutdown_of(app).request()


def server_config(factory: Callable[[], Any]) -> uvicorn.Config:
    """uvicorn settings shared by every service container (``BOMAGENT_HOST``/``_PORT``)."""
    return uvicorn.Config(
        factory,
        factory=True,
        host=os.environ.get("BOMAGENT_HOST", "0.0.0.0"),  # noqa: S104 - container port
        port=int(os.environ.get("BOMAGENT_PORT", "8000")),
        log_config=None,
        proxy_headers=True,  # trusted proxies: uvicorn's FORWARDED_ALLOW_IPS
        timeout_graceful_shutdown=int(os.environ.get(ENV_GRACE_S, DEFAULT_GRACE_S)),
    )


def serve(factory: Callable[[], Any]) -> None:
    """Run ``factory()``'s app until SIGTERM, then shut down gracefully (see module doc)."""
    GracefulServer(server_config(factory)).run()
