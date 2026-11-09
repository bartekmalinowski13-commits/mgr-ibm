"""Enforce coverage thresholds from TESTING.md on a Cobertura coverage.xml.

>= 85 % line coverage for domain packages (packages/py/*), >= 75 % for services.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # trusted input: our own coverage report
from collections import defaultdict
from pathlib import Path

THRESHOLDS = {"packages/py": 0.85, "services": 0.75}
EXCLUDED = ("packages/py/testing/",)


def main(path: str) -> int:
    root = ET.parse(path).getroot()
    sources = [Path(s.text or "") for s in root.iter("source")]
    covered: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        full = next((str(s / filename) for s in sources if (s / filename).exists()), filename)
        rel = full.split(str(Path.cwd()) + "/")[-1]
        if rel.startswith(EXCLUDED):
            continue
        group = next((g for g in THRESHOLDS if rel.startswith(g)), None)
        if group is None:
            continue
        for line in cls.iter("line"):
            covered[group][1] += 1
            covered[group][0] += int(line.get("hits", "0")) > 0
    failed = False
    for group, (hit, total) in sorted(covered.items()):
        ratio = hit / total if total else 1.0
        ok = ratio >= THRESHOLDS[group]
        failed |= not ok
        print(f"{group:12s} {ratio:6.1%} (min {THRESHOLDS[group]:.0%}) {'OK' if ok else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.xml"))
