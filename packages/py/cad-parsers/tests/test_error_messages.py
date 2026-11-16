"""SEC-17: error texts of the parsers are stored in ``files.summary`` and shown in the UI, so
they must not leak file system paths, tracebacks or library internals."""

from __future__ import annotations

import random
import re

import pytest

from bomagent_cad import FileRef, ParseError, parse_files

#: anything that looks like an absolute path, a Python source file, a traceback or site-packages
LEAK = re.compile(
    r"(/(?:home|tmp|usr|var|opt|root|etc|app|src)/\S*|[A-Za-z]:\\\S+|\.py\b|Traceback|"
    r"site-packages|0x[0-9a-fA-F]{6,})"
)

NAMES = [
    "board.dxf",
    "board.kicad_sch",
    "board.kicad_pcb",
    "board.pdf",
    "board.xml",
    "board.edf",
    "board.csv",
    "board.zip",
    "board.tgz",
    "board.dwg",
    "board.sch",
]


def _payloads() -> list[bytes]:
    rng = random.Random(7)
    return [
        b"",
        b"\x00" * 64,
        b"(kicad_sch (version 20231120) (symbol",  # truncated s-expression
        b"0\nSECTION\n2\nENTITIES\n0\nINSERT\n",  # truncated DXF
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer << /Root 9 0 R >>\n%%EOF\n",
        b"<?xml version='1.0'?><IPC-2581><Bom></IPC-2581",  # malformed XML
        b"Reference,Qty,Value\nR1,notanumber,10k\n",
        b"PK\x03\x04" + bytes(rng.randrange(256) for _ in range(200)),
        bytes(rng.randrange(256) for _ in range(512)),
        b"\xe2\x80\xae(kicad_sch)\x00",  # right-to-left override + NUL
    ]


def _error_text(name: str, payload: bytes) -> str | None:
    try:
        parse_files([FileRef(name, payload)])
    except ParseError as exc:
        return f"{exc.code} {exc}"
    except Exception as exc:
        pytest.fail(f"{name}: unexpected {type(exc).__name__}: {exc}")
    return None


def test_parse_error_messages_do_not_leak_internals():
    texts = [
        (name, text)
        for name in NAMES
        for payload in _payloads()
        if (text := _error_text(name, payload)) is not None
    ]
    assert len(texts) > 20  # the crafted inputs really exercise the error paths
    for name, text in texts:
        assert not LEAK.search(text), f"{name}: {text!r}"
        assert len(text) < 1000
