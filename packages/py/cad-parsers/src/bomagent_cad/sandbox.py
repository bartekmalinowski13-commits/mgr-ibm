"""Run ``parse_files`` in a resource-limited child process.

Customer files are untrusted (CLAUDE.md rule 5). Size, entry and decompression limits live in
the parsers; this adds the last line of defence: the parse runs in a separate interpreter
(``python -I``) with ``RLIMIT_AS`` (memory), ``RLIMIT_CPU``, a wall-clock timeout and a
minimal environment, so a hostile file can neither exhaust the worker nor read its secrets
(database URLs, cloud credentials). A child that is killed, times out or exceeds a limit is a
``ParseError`` (``parse.resource_limit`` / ``parse.timeout``): the worker marks the file failed
instead of crashing and redelivering the message forever.

Limits come from ``SandboxLimits`` (defaults overridable with ``BOMAGENT_PARSE_MEMORY_MB``,
``BOMAGENT_PARSE_CPU_SECONDS``, ``BOMAGENT_PARSE_TIMEOUT_SECONDS``). Setting
``BOMAGENT_PARSE_SANDBOX=inprocess`` runs in the calling process (unit tests only).
Memory and CPU limits need the POSIX ``resource`` module; elsewhere only the timeout applies.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from bomagent_bom.model import ParsedDesign
from bomagent_cad.base import FileRef, ParseError
from bomagent_cad.registry import parse_files

MiB = 1024 * 1024
#: cap on the child's reply (a ParsedDesign is small; anything bigger is a misbehaving child)
MAX_REPLY_BYTES = 128 * MiB
_ENV_KEEP = ("LANG", "LC_ALL", "TZ")


@dataclass(frozen=True)
class SandboxLimits:
    memory_bytes: int = 1024 * MiB
    cpu_seconds: int = 60
    timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SandboxLimits:
        env = os.environ if env is None else env
        d = cls()
        return cls(
            memory_bytes=int(env.get("BOMAGENT_PARSE_MEMORY_MB", d.memory_bytes // MiB)) * MiB,
            cpu_seconds=int(env.get("BOMAGENT_PARSE_CPU_SECONDS", d.cpu_seconds)),
            timeout_seconds=float(env.get("BOMAGENT_PARSE_TIMEOUT_SECONDS", d.timeout_seconds)),
        )


def child_env(parent: Mapping[str, str] | None = None) -> dict[str, str]:
    """Minimal environment for the child: no DB URLs, cloud credentials or tokens."""
    parent = os.environ if parent is None else parent
    env = {k: parent[k] for k in _ENV_KEEP if k in parent}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _encode(files: list[FileRef]) -> bytes:
    header = json.dumps({"files": [{"name": f.name, "size": len(f.data)} for f in files]})
    return header.encode() + b"\n" + b"".join(f.data for f in files)


def killed_error(returncode: int, stderr: bytes) -> ParseError:
    """Map an abnormal child exit (SIGXCPU/SIGKILL/SIGSEGV from the limits or the OOM killer)."""
    if returncode < 0 and -returncode in {int(s) for s in signal.Signals}:
        detail = signal.Signals(-returncode).name
    else:
        detail = f"exit {returncode}"
    tail = stderr[-300:].decode("utf-8", "replace")
    if "MemoryError" in tail or "Cannot allocate" in tail:
        return ParseError("parsing exceeded its memory limit", code="parse.resource_limit")
    return ParseError(
        f"parsing exceeded its resource limits ({detail})", code="parse.resource_limit"
    )


def parse_files_sandboxed(
    files: list[FileRef], limits: SandboxLimits | None = None
) -> ParsedDesign:
    if os.environ.get("BOMAGENT_PARSE_SANDBOX", "").lower() == "inprocess":
        return parse_files(files)
    limits = limits or SandboxLimits.from_env()
    cmd = [
        sys.executable,
        "-I",
        "-m",
        "bomagent_cad._sandbox_child",
        str(limits.memory_bytes),
        str(limits.cpu_seconds),
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd,
            input=_encode(files),
            capture_output=True,
            timeout=limits.timeout_seconds,
            env=child_env(),
            cwd="/",
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ParseError(
            f"parsing took longer than {limits.timeout_seconds:g} s", code="parse.timeout"
        ) from exc
    except OSError as exc:  # fork/exec failure (e.g. EAGAIN under a process limit)
        raise ParseError(
            f"the parser could not be started ({type(exc).__name__})", code="parse.resource_limit"
        ) from exc
    if proc.returncode != 0 or not proc.stdout or len(proc.stdout) > MAX_REPLY_BYTES:
        raise killed_error(proc.returncode, proc.stderr)
    try:
        reply = json.loads(proc.stdout.splitlines()[-1])
        failure = (
            None
            if reply["ok"]
            else ParseError(str(reply["message"])[:500], code=str(reply["code"]))
        )
        design = ParsedDesign.model_validate(reply["design"]) if failure is None else None
    except Exception as exc:
        raise ParseError(
            f"the parser returned an invalid reply ({type(exc).__name__})", code="parse.internal"
        ) from exc
    if failure is not None:
        raise failure
    assert design is not None
    return design
