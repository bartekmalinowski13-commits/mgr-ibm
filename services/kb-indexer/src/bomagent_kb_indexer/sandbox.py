"""Knowledge-base text extraction in the resource-limited parse sandbox (ingest review I4).

Datasheets and other KB uploads are customer files like design files (CLAUDE.md rule 5):
pypdf / Docling run in a separate interpreter with ``RLIMIT_AS``, ``RLIMIT_CPU``, a
wall-clock timeout, a minimal environment and the hardening of ``bomagent_cad.sandbox``
(the kb-indexer holds the LLM gateway key and both database roles). Every failure - a
damaged or hostile file, a limit, a timeout - is an :class:`ExtractionError`, which the
handler records as a permanent ``failed`` instead of letting the queue retry it.

Limits: ``BOMAGENT_KB_EXTRACT_MEMORY_MB``, ``BOMAGENT_KB_EXTRACT_CPU_SECONDS``,
``BOMAGENT_KB_EXTRACT_TIMEOUT_SECONDS`` (defaults as for design files; raise the memory
when Docling is enabled). ``BOMAGENT_PARSE_SANDBOX=inprocess`` runs in the calling process
(unit tests only).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from bomagent_cad import ParseError
from bomagent_cad.sandbox import SandboxLimits, run_sandboxed, sandbox_disabled
from bomagent_kb import ExtractedDocument, ExtractionError, Page, extract

CHILD_MODULE = "bomagent_kb_indexer._extract_child"
ENV_PREFIX = "BOMAGENT_KB_EXTRACT_"


def limits_from_env(env: Mapping[str, str] | None = None) -> SandboxLimits:
    return SandboxLimits.from_env(env, prefix=ENV_PREFIX)


def extract_sandboxed(
    name: str, data: bytes, *, use_docling: bool = False, limits: SandboxLimits | None = None
) -> ExtractedDocument:
    """``bomagent_kb.extract`` in the sandbox child. Blocking: call it off the event loop."""
    if sandbox_disabled():
        return extract(name, data, use_docling=use_docling)
    header = json.dumps({"name": name, "size": len(data), "use_docling": use_docling})
    try:
        reply = run_sandboxed(
            CHILD_MODULE, header.encode() + b"\n" + data, limits or limits_from_env()
        )
    except ParseError as exc:  # killed, timed out or garbage: the document is the cause
        raise ExtractionError(str(exc)) from exc
    if not reply["ok"]:
        raise ExtractionError(str(reply.get("message", "extraction failed"))[:500])
    try:
        doc = reply["document"]
        return ExtractedDocument(
            pages=[Page(int(p["number"]), str(p["text"])) for p in doc["pages"]],
            mime_type=str(doc["mime_type"]),
            limitations=[str(x) for x in doc["limitations"]],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExtractionError(f"invalid extraction reply ({type(exc).__name__})") from exc
