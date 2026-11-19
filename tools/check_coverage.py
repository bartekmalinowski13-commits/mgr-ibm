"""Enforce the coverage rules from TESTING.md on a Cobertura coverage.xml.

* >= 85 % line coverage for the domain packages (``packages/py/*``), >= 75 % for services.
* An empty report, or a group without any measured line, fails (a misconfigured ``--cov``
  source must not pass silently).
* No drop in a PR: each package (``packages/py/<name>``, ``services/<name>``) is compared with
  the committed baseline (``tools/coverage-baseline.json``); a drop of more than
  ``TOLERANCE_PP`` percentage points, a baselined package missing from the report, or a
  package missing from the baseline fails (the baseline is owner-reviewed, CODEOWNERS).
  Raise the baseline when coverage rises: ``--write-baseline tools/coverage-baseline.json``.

Usage: check_coverage.py [coverage.xml] [--baseline FILE] [--write-baseline FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET  # trusted input: our own coverage report
from collections import defaultdict
from pathlib import Path

THRESHOLDS = {"packages/py": 0.85, "services": 0.75}
EXCLUDED = ("packages/py/testing/",)
#: line coverage may move a little between runs (timing-dependent branches)
TOLERANCE_PP = 0.5
DEFAULT_BASELINE = Path(__file__).resolve().parent / "coverage-baseline.json"


def _lines(path: str) -> dict[str, list[int]]:
    """{package (``packages/py/<name>`` / ``services/<name>``): [hit, total]}."""
    root = ET.parse(path).getroot()
    sources = [Path(s.text or "") for s in root.iter("source")]
    per_package: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        full = next((str(s / filename) for s in sources if (s / filename).exists()), filename)
        rel = full.split(str(Path.cwd()) + "/")[-1]
        for source in sources:  # a report written elsewhere: make it relative to its source
            prefix = str(source).rstrip("/") + "/"
            if rel.startswith(prefix):
                rel = rel[len(prefix) :]
        if rel.startswith(EXCLUDED):
            continue
        group = next((g for g in THRESHOLDS if rel.startswith(g + "/")), None)
        if group is None:
            continue
        name = rel[len(group) + 1 :].split("/", 1)[0]
        counts = per_package[f"{group}/{name}"]
        for line in cls.iter("line"):
            counts[1] += 1
            counts[0] += int(line.get("hits", "0")) > 0
    return dict(per_package)


def _pct(hit: int, total: int) -> float:
    return round(100.0 * hit / total, 2) if total else 0.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="check_coverage.py")
    p.add_argument("report", nargs="?", default="coverage.xml")
    p.add_argument("--baseline", type=Path, help="fail on a per-package drop against this")
    p.add_argument("--write-baseline", type=Path, help="write per-package coverage here")
    args = p.parse_args(argv)

    packages = _lines(args.report)
    failed = False
    for group, minimum in THRESHOLDS.items():
        hit = sum(v[0] for k, v in packages.items() if k.startswith(group + "/"))
        total = sum(v[1] for k, v in packages.items() if k.startswith(group + "/"))
        if total == 0:
            print(f"{group:28s} no lines measured - is --cov pointing at the sources? FAIL")
            failed = True
            continue
        ok = hit / total >= minimum
        failed |= not ok
        print(f"{group:28s} {hit / total:6.1%} (min {minimum:.0%}) {'OK' if ok else 'FAIL'}")
    for name, (hit, total) in sorted(packages.items()):
        print(f"  {name:26s} {_pct(hit, total):6.2f} %")

    current = {k: _pct(*v) for k, v in packages.items() if v[1]}
    if args.baseline is not None:
        baseline: dict[str, float] = json.loads(args.baseline.read_text())
        for name, before in sorted(baseline.items()):
            now = current.get(name)
            if now is None:
                print(f"{name}: in the baseline but not in the report FAIL")
                failed = True
            elif now < before - TOLERANCE_PP:
                print(f"{name}: coverage dropped {before:.2f} % -> {now:.2f} % FAIL")
                failed = True
        for name in sorted(set(current) - set(baseline)):
            print(f"{name}: not in {args.baseline.name} - add it (--write-baseline) FAIL")
            failed = True
        if not failed:
            print(f"no drop against {args.baseline.name} (tolerance {TOLERANCE_PP} pp)")
    if args.write_baseline is not None and not failed:
        args.write_baseline.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.write_baseline}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
