"""Licence gate (SEC-10): fail on forbidden licences, warn on unknown ones.

Policy source: docs/DECISIONS_LOG.md (2026-11-09) rejected MinIO (AGPLv3) and PyMuPDF (AGPL-3.0)
because a SaaS cannot ship them without a commercial licence. The gate therefore forbids the
network-copyleft classes AGPL and SSPL. No other class is forbidden by an ADR or SECURITY.md, so
nothing else fails the build: a distribution whose licence cannot be classified is listed as a
warning for a human to review, never as a failure.

Usage::

    python tools/license_gate.py python                           # installed distributions
    pnpm licenses list --json | python tools/license_gate.py js   # pnpm workspace

Exit code 1 only when a forbidden licence is found (2 when nothing was scanned). ``--allow NAME``
(repeatable) records a reviewed exception for a package whose metadata is known to be wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from importlib import metadata

_FORBIDDEN = re.compile(r"\b(AGPL|Affero|SSPL|Server[ -]Side[ -]Public)", re.IGNORECASE)
# Recognisable licences (acceptable, or copyleft that no ADR forbids). Only used to separate
# "known" from "unknown" for the warning list.
_KNOWN = re.compile(
    r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|MPL|Mozilla|LGPL|GPL|EPL|Eclipse|"
    r"Unlicense|CC0|0BSD|Zlib|HPND|BlueOak|Artistic|WTFPL|Public Domain|CC-BY|PostgreSQL|"
    r"Unicode|OFL|ZPL|BSL-1\.0|Boost|UPL|Python-2\.0|CNRI)",
    re.IGNORECASE,
)
_CLASSIFIER_PREFIX = "License :: "


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    licence: str


@dataclass
class Report:
    forbidden: list[Package] = field(default_factory=list)
    unknown: list[Package] = field(default_factory=list)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.forbidden


def classify(licence: str) -> str:
    """Return ``forbidden``, ``known`` or ``unknown`` for a licence string or expression."""
    if _FORBIDDEN.search(licence):
        return "forbidden"
    if _KNOWN.search(licence):
        return "known"
    return "unknown"


def evaluate(packages: Iterable[Package], allow: Iterable[str] = ()) -> Report:
    allowed = {a.lower() for a in allow}
    report = Report()
    for pkg in packages:
        report.checked += 1
        if pkg.name.lower() in allowed:
            continue
        kind = classify(pkg.licence)
        if kind == "forbidden":
            report.forbidden.append(pkg)
        elif kind == "unknown":
            report.unknown.append(pkg)
    return report


def _python_licence(meta: metadata.PackageMetadata) -> str:
    parts: list[str] = []
    expression = meta.get("License-Expression")
    if expression:
        parts.append(expression)
    parts.extend(
        c.removeprefix(_CLASSIFIER_PREFIX)
        for c in meta.get_all("Classifier") or []
        if c.startswith(_CLASSIFIER_PREFIX)
    )
    free_text = (meta.get("License") or "").strip()
    # Some packages put the whole licence text into the field: keep only the first line.
    if free_text and free_text.upper() != "UNKNOWN":
        parts.append(free_text.splitlines()[0][:200])
    return " | ".join(parts)


def python_packages() -> Iterator[Package]:
    seen: set[str] = set()
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name or name.lower() in seen or name.lower().startswith("bomagent-"):
            continue  # first-party workspace members are proprietary by design
        seen.add(name.lower())
        yield Package(name, dist.version, _python_licence(dist.metadata))


def js_packages(document: object) -> Iterator[Package]:
    """Parse ``pnpm licenses list --json``: ``{"<licence>": [{"name", "versions": [...]}]}``."""
    if not isinstance(document, dict):
        raise TypeError("expected a JSON object keyed by licence")
    for licence, entries in document.items():
        for entry in entries:
            versions = entry.get("versions") or [""]
            yield Package(str(entry["name"]), ", ".join(versions), str(licence))


def _print(report: Report, ecosystem: str) -> None:
    print(f"licence gate ({ecosystem}): {report.checked} packages checked")
    if report.unknown:
        print(f"WARNING: {len(report.unknown)} package(s) with an unrecognised licence (review):")
        for p in sorted(report.unknown, key=lambda x: x.name.lower()):
            print(f"  - {p.name} {p.version}: {p.licence or '<none declared>'}")
    if report.forbidden:
        print(f"FAIL: {len(report.forbidden)} package(s) under a forbidden licence (AGPL/SSPL):")
        for p in sorted(report.forbidden, key=lambda x: x.name.lower()):
            print(f"  - {p.name} {p.version}: {p.licence}")


def main(argv: list[str] | None = None, stdin: str | None = None) -> int:
    parser = argparse.ArgumentParser(description="Licence gate (AGPL/SSPL fail, unknown warn)")
    parser.add_argument("ecosystem", choices=["python", "js"])
    parser.add_argument("--allow", action="append", default=[], metavar="NAME")
    args = parser.parse_args(argv)
    if args.ecosystem == "python":
        packages = list(python_packages())
    else:
        raw = stdin if stdin is not None else sys.stdin.read()
        packages = list(js_packages(json.loads(raw)))
    if not packages:
        print("licence gate: no packages found - refusing to pass vacuously", file=sys.stderr)
        return 2
    report = evaluate(packages, args.allow)
    _print(report, args.ecosystem)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
