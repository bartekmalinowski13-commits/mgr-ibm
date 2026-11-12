"""Build the sample design pack (``evals/samples``, CC0-1.0, self-authored).

Five small but realistic biomedical designs in different formats, each with a hand-checked
``reference_bom.csv``:

* three KiCad projects copied from ``evals/fixtures/kicad`` (KiCad 6 / 8 / 9),
* ``ecg-patch`` exported as an EDIF 2.0.0 netlist (non-KiCad),
* ``thermometer`` exported as a PDF BOM table.

The two extra designs are defined in ``tools/fixtures/gen_kicad_fixtures.py``; their KiCad
sources are only an intermediate step (the pack ships the exported format, as a customer
would hand it over).

    uv run python tools/make_sample_pack.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "fixtures"))

import gen_kicad_fixtures as gen  # noqa: E402
import make_format_fixtures as fmt  # noqa: E402
from bomagent_cad import FileRef, parse_files  # noqa: E402

OUT = ROOT / "services" / "api" / "src" / "bomagent_api" / "samples" / "data"
KICAD = ROOT / "evals" / "fixtures" / "kicad"
KICAD_COPIES = {"ecg-frontend": "ecg-frontend", "eeg-2ch": "eeg-2ch", "pulse-oximeter": "pulse-ox"}


def copy_kicad(slug: str, src_name: str) -> None:
    dest = OUT / slug
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted((KICAD / src_name).iterdir()):
        if path.suffix.startswith(".kicad") or path.name == "reference_bom.csv":
            shutil.copyfile(path, dest / path.name)


def build_exports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for project in (gen.ecg_patch(), gen.thermometer()):
            src = Path(tmp) / project.name
            src.mkdir()
            gen.render(project, src)
            gen.reference_bom(project, src)
            design = parse_files(
                [
                    FileRef.from_path(p)
                    for p in sorted(src.iterdir())
                    if p.suffix.startswith(".kicad")
                ]
            )
            dest = OUT / project.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / "reference_bom.csv", dest / "reference_bom.csv")
            if project.name == "ecg-patch":
                (dest / "ecg-patch.edf").write_text(fmt.edif(design), encoding="utf-8")
            else:
                (dest / "thermometer-bom.pdf").write_bytes(
                    fmt.pdf_bom(src / "reference_bom.csv", "Digital thermometer - BOM")
                )


def main() -> None:
    for slug, src_name in KICAD_COPIES.items():
        copy_kicad(slug, src_name)
    build_exports()
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
