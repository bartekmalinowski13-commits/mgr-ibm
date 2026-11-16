"""Malware scanner (audit SEC-09): EICAR, a fake clamd over TCP and a unix socket, fail closed."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from bomagent_cad import FileRef
from bomagent_ingest.handler import IngestWorker
from bomagent_ingest.scanner import (
    EICAR_SIGNATURE,
    ClamdScanner,
    EicarScanner,
    MalwareDetectedError,
    NoopScanner,
    ScannerError,
    ScanResult,
    scanner_from_env,
)


class FakeClamd:
    """Speaks just enough of clamd: ``zINSTREAM`` with EICAR detection and canned errors."""

    def __init__(self, *, reply: bytes | None = None, hang: bool = False) -> None:
        self.reply = reply
        self.hang = hang
        self.received: list[bytes] = []
        self.commands: list[bytes] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            self.commands.append(await reader.readuntil(b"\0"))
            if self.hang:
                await asyncio.sleep(60)
            data = b""
            while True:
                (size,) = struct.unpack(">I", await reader.readexactly(4))
                if size == 0:
                    break
                data += await reader.readexactly(size)
            self.received.append(data)
            if self.reply is not None:
                writer.write(self.reply)
            elif EICAR_SIGNATURE in data:
                writer.write(b"stream: Eicar-Signature FOUND\0")
            else:
                writer.write(b"stream: OK\0")
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


@pytest.fixture
async def clamd_tcp() -> AsyncIterator[tuple[FakeClamd, str]]:
    fake = FakeClamd()
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield fake, f"tcp://127.0.0.1:{port}"


async def test_eicar_scanner_flags_the_test_string_only() -> None:
    scanner = EicarScanner()
    assert (await scanner.scan("a.txt", b"hello")).clean
    hit = await scanner.scan("a.txt", b"prefix" + EICAR_SIGNATURE + b"\r\n")
    assert not hit.clean
    assert hit.signature == "Eicar-Test-Signature"


async def test_noop_scanner_accepts_everything() -> None:
    assert (await NoopScanner().scan("a.txt", EICAR_SIGNATURE)).clean


async def test_clamd_tcp_clean_and_infected(clamd_tcp) -> None:
    fake, address = clamd_tcp
    scanner = ClamdScanner(address)
    big = b"x" * (200 * 1024)  # several INSTREAM chunks
    assert await scanner.scan("ok.bin", big) == ScanResult(clean=True)
    assert fake.received == [big]
    assert fake.commands == [b"zINSTREAM\0"]
    verdict = await scanner.scan("bad.bin", EICAR_SIGNATURE)
    assert verdict == ScanResult(clean=False, signature="Eicar-Signature")


async def test_clamd_unix_socket(tmp_path: Path) -> None:
    fake = FakeClamd()
    sock = str(tmp_path / "clamd.sock")
    server = await asyncio.start_unix_server(fake.handle, sock)
    async with server:
        scanner = ClamdScanner(f"unix://{sock}")
        assert (await scanner.scan("ok", b"data")).clean
        assert not (await scanner.scan("bad", EICAR_SIGNATURE)).clean


async def test_clamd_errors_fail_closed() -> None:
    fake = FakeClamd(reply=b"INSTREAM size limit exceeded. ERROR\0")
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        with pytest.raises(ScannerError):
            await ClamdScanner(f"tcp://127.0.0.1:{port}").scan("a", b"data")


async def test_clamd_unreachable_and_timeout_fail_closed() -> None:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    with pytest.raises(ScannerError):  # nothing listens any more
        await ClamdScanner(f"tcp://127.0.0.1:{port}").scan("a", b"data")

    hang = FakeClamd(hang=True)
    slow = await asyncio.start_server(hang.handle, "127.0.0.1", 0)
    async with slow:
        port = slow.sockets[0].getsockname()[1]
        with pytest.raises(ScannerError):
            await ClamdScanner(f"tcp://127.0.0.1:{port}", timeout_s=0.2).scan("a", b"data")


@pytest.mark.parametrize("address", ["", "localhost:3310", "tcp://", "unix://"])
def test_invalid_clamd_addresses_are_rejected(address: str) -> None:
    with pytest.raises(ValueError, match="clamd"):
        ClamdScanner(address)


def test_scanner_from_env_is_off_unless_configured() -> None:
    assert isinstance(scanner_from_env({}), EicarScanner)
    assert isinstance(scanner_from_env({"BOMAGENT_MALWARE_SCAN_CLAMD_ADDR": " "}), EicarScanner)
    configured = scanner_from_env(
        {
            "BOMAGENT_MALWARE_SCAN_CLAMD_ADDR": "tcp://clamd:3310",
            "BOMAGENT_MALWARE_SCAN_TIMEOUT_S": "5",
        }
    )
    assert isinstance(configured, ClamdScanner)
    assert configured.timeout_s == 5.0


class _Recorder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def scan(self, name: str, data: bytes) -> ScanResult:
        self.seen.append(name)
        return await EicarScanner().scan(name, data)


async def test_worker_rejects_the_whole_project_before_parsing() -> None:
    scanner = _Recorder()
    worker = IngestWorker(engine=None, store=None, scanner=scanner)  # type: ignore[arg-type]
    files = [FileRef("a.kicad_sch", b"(kicad_sch)"), FileRef("b.kicad_pcb", EICAR_SIGNATURE)]
    with pytest.raises(MalwareDetectedError) as caught:
        await worker._scan_all(files)
    assert caught.value.findings == {"b.kicad_pcb": "Eicar-Test-Signature"}
    assert scanner.seen == ["a.kicad_sch", "b.kicad_pcb"]  # every file is scanned
    await worker._scan_all(files[:1])  # clean projects pass


async def test_worker_propagates_scanner_errors() -> None:
    class Broken:
        async def scan(self, name: str, data: bytes) -> ScanResult:
            raise ScannerError("down")

    worker = IngestWorker(engine=None, store=None, scanner=Broken())  # type: ignore[arg-type]
    with pytest.raises(ScannerError):
        await worker._scan_all([FileRef("a", b"x")])
