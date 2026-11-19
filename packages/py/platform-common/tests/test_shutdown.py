"""Process shutdown: SIGTERM ends long-lived streams and stops consumers before uvicorn
waits for open connections (OPS: graceful shutdown with open SSE streams)."""

from __future__ import annotations

import asyncio
import signal
import threading

import uvicorn
from fastapi import FastAPI

from bomagent_common.config import ServiceSettings
from bomagent_common.service import create_service_app
from bomagent_common.shutdown import (
    DEFAULT_GRACE_S,
    GracefulServer,
    ShutdownSignal,
    server_config,
    shutdown_of,
)


async def test_sleep_times_out_without_a_request():
    sig = ShutdownSignal()
    assert await sig.sleep(0.01) is False
    assert not sig.requested


async def test_request_wakes_sleepers_at_once():
    sig = ShutdownSignal()
    sleeper = asyncio.create_task(sig.sleep(30))
    await asyncio.sleep(0)
    sig.request()
    assert await asyncio.wait_for(sleeper, timeout=1) is True
    assert sig.requested
    assert await sig.sleep(30) is True  # later sleepers return immediately


async def test_request_from_another_thread_reaches_the_loop():
    sig = ShutdownSignal()
    seen: list[str] = []
    sig.on_request(lambda: seen.append("stop"))
    sleeper = asyncio.create_task(sig.sleep(30))
    await asyncio.sleep(0)
    t = threading.Thread(target=sig.request)  # like a signal handler outside the loop
    t.start()
    t.join()
    assert await asyncio.wait_for(sleeper, timeout=1) is True
    assert seen == ["stop"]


async def test_callbacks_run_once():
    sig = ShutdownSignal()
    calls: list[int] = []
    sig.on_request(lambda: calls.append(1))
    await sig.sleep(0)  # binds the loop
    sig.request()
    sig.request()
    await asyncio.sleep(0.01)
    assert calls == [1]


def test_every_service_app_has_a_shutdown_signal():
    app = create_service_app(ServiceSettings(), version="t")
    assert isinstance(shutdown_of(app), ShutdownSignal)
    assert shutdown_of(app) is shutdown_of(app)


def test_shutdown_of_a_plain_app_is_created_on_demand():
    app = FastAPI()
    assert shutdown_of(app) is shutdown_of(app)


def test_server_handle_exit_requests_shutdown_of_the_app():
    app = create_service_app(ServiceSettings(), version="t")
    config = server_config(lambda: app)
    server = GracefulServer(config)
    config.load()
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit
    assert shutdown_of(app).requested


def test_server_config_bounds_the_graceful_shutdown(monkeypatch):
    monkeypatch.setenv("BOMAGENT_PORT", "8123")
    config = server_config(FastAPI)
    assert isinstance(config, uvicorn.Config)
    assert config.timeout_graceful_shutdown == DEFAULT_GRACE_S
    assert config.port == 8123
    assert config.proxy_headers is True
    monkeypatch.setenv("BOMAGENT_SHUTDOWN_GRACE_S", "5")
    assert server_config(FastAPI).timeout_graceful_shutdown == 5
