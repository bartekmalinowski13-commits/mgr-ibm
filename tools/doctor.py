"""`just doctor`: check that the local toolchain can build and test the repo (DOC-04).

Read-only: runs `<tool> --version` and prints what is missing or too old, with an install
hint. Exit code 1 when a required tool is missing; optional tools only warn.
Standard library only, so it works before `just bootstrap`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    name: str
    version_cmd: list[str]
    minimum: tuple[int, ...]
    hint: str
    required: bool = True


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    required: bool
    detail: str
    hint: str


TOOLS = [
    Tool(
        "uv", ["uv", "--version"], (0, 5), "https://docs.astral.sh/uv/getting-started/installation/"
    ),
    Tool("python", [sys.executable, "--version"], (3, 12), "uv python install 3.12"),
    Tool("node", ["node", "--version"], (22,), "install Node 22+ (https://nodejs.org or nvm)"),
    Tool(
        "pnpm",
        ["pnpm", "--version"],
        (10,),
        "corepack enable && corepack prepare pnpm@10.28.0 --activate",
    ),
    Tool("just", ["just", "--version"], (1, 0), "https://just.systems/man/en/packages.html"),
    Tool("git", ["git", "--version"], (2, 30), "install git"),
    Tool(
        "docker",
        ["docker", "--version"],
        (24,),
        "needed for `just up`, Testcontainers integration tests (Postgres+pgvector)",
        required=False,
    ),
]


def parse_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+)+", text)
    return tuple(int(p) for p in match.group().split(".")) if match else None


def run_version(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    return (done.stdout or done.stderr).strip()


def check_tool(tool: Tool) -> Result:
    def fail(detail: str) -> Result:
        return Result(tool.name, False, tool.required, detail, tool.hint)

    if shutil.which(tool.version_cmd[0]) is None:
        return fail("missing")
    try:
        output = run_version(tool.version_cmd)
    except (OSError, subprocess.SubprocessError) as exc:
        return fail(f"cannot run: {type(exc).__name__}")
    found = parse_version(output)
    need = ".".join(map(str, tool.minimum))
    if found is None:
        return fail(f"cannot read version from {output!r}")
    shown = ".".join(map(str, found))
    if found < tool.minimum:
        return fail(f"{shown} found, need >= {need}")
    return Result(tool.name, True, tool.required, shown, tool.hint)


def main(argv: list[str] | None = None) -> int:
    del argv
    results = [check_tool(t) for t in TOOLS]
    for r in results:
        mark = "ok  " if r.ok else ("FAIL" if r.required else "warn")
        print(f"[{mark}] {r.name:<7} {r.detail}")
        if not r.ok:
            print(f"        -> {r.hint}")
    failed = [r for r in results if not r.ok and r.required]
    if failed:
        print(
            f"\n{len(failed)} required tool(s) missing or too old: "
            + ", ".join(r.name for r in failed)
        )
        return 1
    print("\nall required tools present; next: `just bootstrap`")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
