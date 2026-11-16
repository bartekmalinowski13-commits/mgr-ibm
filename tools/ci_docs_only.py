"""Is a change set documentation-only? (OPS-07)

Reads changed paths (one per line) on stdin and prints ``docs_only=true|false`` for
``$GITHUB_OUTPUT``. Used by the ``changes`` job of ``.github/workflows/pr.yml`` to skip
only the heavy image/stack jobs. Fails safe: anything unknown, empty or odd is ``false``.
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath


def _is_doc(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or ".." in parts or path.startswith("/"):
        return False
    return parts[0] == "docs" or (len(parts) == 1 and path.endswith(".md"))


def is_docs_only(paths: list[str]) -> bool:
    return bool(paths) and all(_is_doc(p) for p in paths)


def main(argv: list[str] | None = None) -> int:
    del argv
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print(f"docs_only={'true' if is_docs_only(paths) else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
