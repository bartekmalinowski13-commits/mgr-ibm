"""Malware scanning of uploaded files before any parser runs (audit SEC-09).

Customer files are untrusted (CLAUDE.md rule 5). The ingest worker scans every file it loads
and refuses the whole project when one is infected, so no parser ever sees it.

Scanners implement :class:`FileScanner`:

* :class:`NoopScanner` - accepts everything (tests, explicit opt-out).
* :class:`EicarScanner` - the default: always on, dependency-free, rejects the EICAR
  anti-malware test string. It is **not** a real scanner; it proves the wiring end to end.
* :class:`ClamdScanner` - ``clamd`` over TCP or a unix socket (``INSTREAM``). Off unless
  ``BOMAGENT_MALWARE_SCAN_CLAMD_ADDR`` is set. Fails closed: when clamd is unreachable or
  answers with an error the file is *not* treated as clean (:class:`ScannerError`, the queue
  message is retried).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from bomagent_common.logging import get_logger

log = get_logger(__name__)

ENV_CLAMD_ADDR = "BOMAGENT_MALWARE_SCAN_CLAMD_ADDR"
ENV_CLAMD_TIMEOUT = "BOMAGENT_MALWARE_SCAN_TIMEOUT_S"
DEFAULT_CLAMD_TIMEOUT_S = 30.0
DEFAULT_CLAMD_PORT = 3310
_CHUNK = 64 * 1024

# Standard EICAR anti-malware test file (https://www.eicar.org): harmless by design.
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class ScannerError(RuntimeError):
    """The scan could not be completed; the file must not be treated as clean."""


class MalwareDetectedError(Exception):
    """One or more files were flagged. Signatures are for audit/log only, never for users."""

    def __init__(self, findings: Mapping[str, str]) -> None:
        super().__init__("malware detected")
        self.findings = dict(findings)  # file name -> signature


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None


class FileScanner(Protocol):
    async def scan(self, name: str, data: bytes) -> ScanResult: ...


class NoopScanner:
    async def scan(self, name: str, data: bytes) -> ScanResult:
        return ScanResult(clean=True)


class EicarScanner:
    async def scan(self, name: str, data: bytes) -> ScanResult:
        if EICAR_SIGNATURE in data:
            return ScanResult(clean=False, signature="Eicar-Test-Signature")
        return ScanResult(clean=True)


class ClamdScanner:
    """``clamd`` ``INSTREAM`` client. ``address``: ``tcp://host[:port]`` or ``unix:///path``."""

    def __init__(self, address: str, *, timeout_s: float = DEFAULT_CLAMD_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self._unix: str | None = None
        self._host = ""
        self._port = DEFAULT_CLAMD_PORT
        if address.startswith("unix://"):
            self._unix = address.removeprefix("unix://")
            if not self._unix:
                raise ValueError("empty clamd unix socket path")
        elif address.startswith("tcp://"):
            host, _, port = address.removeprefix("tcp://").partition(":")
            if not host:
                raise ValueError("empty clamd host")
            self._host = host
            self._port = int(port) if port else DEFAULT_CLAMD_PORT
        else:
            raise ValueError("clamd address must start with tcp:// or unix://")

    async def scan(self, name: str, data: bytes) -> ScanResult:
        try:
            return await asyncio.wait_for(self._scan(data), self.timeout_s)
        except (TimeoutError, OSError) as exc:
            raise ScannerError(f"clamd unavailable: {type(exc).__name__}") from exc

    async def _scan(self, data: bytes) -> ScanResult:
        if self._unix:
            reader, writer = await asyncio.open_unix_connection(self._unix)
        else:
            reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), _CHUNK):
                chunk = data[i : i + _CHUNK]
                writer.write(struct.pack(">I", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            reply = (await reader.readuntil(b"\0")).rstrip(b"\0").decode("utf-8", "replace")
        except asyncio.IncompleteReadError as exc:
            raise ScannerError("clamd closed the connection without a verdict") from exc
        finally:
            writer.close()
            with contextlib.suppress(OSError):  # peer already gone
                await writer.wait_closed()
        return _parse_reply(reply)


def _parse_reply(reply: str) -> ScanResult:
    verdict = reply.partition(":")[2].strip()
    if verdict == "OK":
        return ScanResult(clean=True)
    if verdict.endswith(" FOUND"):
        return ScanResult(clean=False, signature=verdict.removesuffix(" FOUND")[:128])
    raise ScannerError(f"clamd error: {verdict[:120] or 'empty reply'}")


def scanner_from_env(env: Mapping[str, str] | None = None) -> FileScanner:
    """ClamAV when ``BOMAGENT_MALWARE_SCAN_CLAMD_ADDR`` is set, else the EICAR scanner."""
    env = os.environ if env is None else env
    address = env.get(ENV_CLAMD_ADDR, "").strip()
    if not address:
        return EicarScanner()
    timeout = float(env.get(ENV_CLAMD_TIMEOUT) or DEFAULT_CLAMD_TIMEOUT_S)
    log.info("malware_scanner_clamd_enabled")
    return ClamdScanner(address, timeout_s=timeout)
