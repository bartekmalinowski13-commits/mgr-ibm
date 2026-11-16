"""Child process entry point of the parse sandbox (``python -I -m bomagent_cad._sandbox_child``).

Protocol: argv = ``<memory_bytes> <cpu_seconds>``. stdin = one JSON header line
``{"files": [{"name": ..., "size": ...}]}`` followed by the raw bytes of each file.
stdout (the original descriptor, saved before the parser runs) = one JSON line, either
``{"ok": true, "design": {...}, "hardening": {...}}`` or
``{"ok": false, "code": ..., "message": ...}``.
"""

from __future__ import annotations

import json
import os
import sys

_PR_SET_NO_NEW_PRIVS = 38
_CLONE_NEWUSER = 0x10000000
_CLONE_NEWNET = 0x40000000
#: descriptors the child needs: stdin, stdout, stderr, the saved result descriptor, a spare
_MAX_OPEN_FILES = 32


def _prctl(option: int, arg: int) -> int:
    if not sys.platform.startswith("linux"):
        return -1
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    return int(libc.prctl(option, arg, 0, 0, 0))


def _unshare_network() -> bool:
    """Leave the network namespace (a new, empty one has no interfaces up, not even loopback).

    Needs CAP_SYS_ADMIN or an unprivileged user namespace, which containers often forbid and
    which a multithreaded process cannot create: best effort, the result is reported."""
    if not sys.platform.startswith("linux"):
        return False
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    return bool(
        libc.unshare(_CLONE_NEWNET) == 0 or libc.unshare(_CLONE_NEWUSER | _CLONE_NEWNET) == 0
    )


def _limit(kind: str, value: int) -> None:
    try:
        import resource

        res = getattr(resource, kind)
        resource.setrlimit(res, (value, value))
    except (ImportError, ValueError, OSError):  # unsupported platform: wall clock still applies
        pass


def apply_hardening() -> dict[str, bool]:
    """Last-line restrictions applied after the imports and before the input is parsed.

    ``no_new_privs`` (no setuid/file-capability escalation), no core files, a small file
    descriptor table, no writes to regular files (``RLIMIT_FSIZE`` 0; Python ignores
    SIGXFSZ, so a write fails with ``OSError`` instead of killing the child) and, where the
    kernel allows it, an empty network namespace. Returns what took effect.
    """
    _limit("RLIMIT_CORE", 0)
    _limit("RLIMIT_NOFILE", _MAX_OPEN_FILES)
    _limit("RLIMIT_FSIZE", 0)
    return {
        "no_new_privs": _prctl(_PR_SET_NO_NEW_PRIVS, 1) == 0,
        "network_isolated": _unshare_network(),
    }


def main(argv: list[str]) -> int:
    memory_bytes, cpu_seconds = int(argv[1]), int(argv[2])
    # keep the real stdout for the result; whatever a library prints goes to stderr
    result_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)

    # heavy imports first, limits afterwards: the limits bound the work on the input
    from bomagent_cad.base import FileRef, ParseError
    from bomagent_cad.registry import parse_files

    hardening = apply_hardening()
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
        return reply({"ok": True, "design": design.model_dump(mode="json"), "hardening": hardening})
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
