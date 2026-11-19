"""Sandbox child for KB extraction (``python -I -m bomagent_kb_indexer._extract_child``).

Protocol (``bomagent_cad._sandbox_child.serve``): argv = ``<memory_bytes> <cpu_seconds>``;
stdin = one JSON header line ``{"name", "size", "use_docling"}`` followed by the file's
bytes; stdout = one JSON line ``{"ok": true, "document": {...}}`` or
``{"ok": false, "code": ..., "message": ...}``.
"""

from __future__ import annotations

import sys
from typing import Any, BinaryIO

from bomagent_cad._sandbox_child import Work, serve


def _load() -> Work:
    from bomagent_kb import ExtractionError, extract

    def work(header: dict[str, Any], stdin: BinaryIO) -> dict[str, object]:
        data = stdin.read(int(header["size"]))
        try:
            doc = extract(str(header["name"]), data, use_docling=bool(header.get("use_docling")))
        except ExtractionError as exc:  # keep the user-facing reason
            return {"ok": False, "code": "kb.extraction_failed", "message": str(exc)}
        return {
            "ok": True,
            "document": {
                "pages": [{"number": p.number, "text": p.text} for p in doc.pages],
                "mime_type": doc.mime_type,
                "limitations": list(doc.limitations),
            },
        }

    return work


if __name__ == "__main__":
    sys.exit(serve(sys.argv, _load))
