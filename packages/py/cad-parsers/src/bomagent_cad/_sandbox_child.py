"""Child process entry point of the parse sandbox (``python -I -m bomagent_cad._sandbox_child``).

Protocol: argv = ``<memory_bytes> <cpu_seconds>``. stdin = one JSON header line
``{"files": [{"name": ..., "size": ...}]}`` followed by the raw bytes of each file.
stdout (the original descriptor, saved before the parser runs) = one JSON line, either
``{"ok": true, "design": {...}}`` or ``{"ok": false, "code": ..., "message": ...}``.
"""

from __future__ import annotations

import json
import os
import sys


def _limit(kind: str, value: int) -> None:
    try:
        import resource

        res = getattr(resource, kind)
        resource.setrlimit(res, (value, value))
    except (ImportError, ValueError, OSError):  # unsupported platform: wall clock still applies
        pass


def main(argv: list[str]) -> int:
    memory_bytes, cpu_seconds = int(argv[1]), int(argv[2])
    # keep the real stdout for the result; whatever a library prints goes to stderr
    result_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)

    # heavy imports first, limits afterwards: the limits bound the work on the input
    from bomagent_cad.base import FileRef, ParseError
    from bomagent_cad.registry import parse_files

    _limit("RLIMIT_CORE", 0)
    _limit("RLIMIT_CPU", cpu_seconds)
    _limit("RLIMIT_AS", memory_bytes)

    def reply(payload: dict[str, object]) -> int:
        result_out.write(json.dumps(payload).encode() + b"\n")
        result_out.flush()
        return 0

    try:
        stdin = sys.stdin.buffer
        header = json.loads(stdin.readline())
        files = []
        for entry in header["files"]:
            data = stdin.read(int(entry["size"]))
            files.append(FileRef(str(entry["name"]), data))
        design = parse_files(files)
        return reply({"ok": True, "design": design.model_dump(mode="json")})
    except MemoryError:
        return reply(
            {"ok": False, "code": "parse.resource_limit", "message": "memory limit exceeded"}
        )
    except ParseError as exc:
        return reply({"ok": False, "code": exc.code, "message": str(exc)})
    except Exception as exc:
        return reply(
            {
                "ok": False,
                "code": "parse.internal",
                "message": f"the file could not be read ({type(exc).__name__})",
            }
        )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
