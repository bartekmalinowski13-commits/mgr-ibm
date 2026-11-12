"""The sample catalogue: which design files make up each sample project.

The files live in ``data/`` (also reachable as ``evals/samples``) and are self-authored
(CC0-1.0). The reference BOMs and READMEs next to them are not uploaded to a tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SAMPLE_PREFIX = "[Sample] "
DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Sample:
    key: str  # stable identifier and folder name; unique per organisation
    title: str
    description: str
    files: tuple[str, ...]

    @property
    def project_name(self) -> str:
        return f"{SAMPLE_PREFIX}{self.title}"

    @property
    def directory(self) -> Path:
        return DATA_DIR / self.key


SAMPLES: tuple[Sample, ...] = (
    Sample(
        "ecg-frontend",
        "ECG front-end",
        "Sample design (CC0): 3-lead ECG analog front end, KiCad 8 with hierarchical sheets,"
        " a DNP part and parts without MPN. You can delete this project.",
        ("ecg-frontend.kicad_sch", "afe.kicad_sch", "power.kicad_sch", "ecg-frontend.kicad_pro"),
    ),
    Sample(
        "eeg-2ch",
        "EEG 2-channel",
        "Sample design (CC0): two-channel EEG board, KiCad 9, one sheet used twice."
        " You can delete this project.",
        ("eeg-2ch.kicad_sch", "channel.kicad_sch", "eeg-2ch.kicad_pro"),
    ),
    Sample(
        "pulse-oximeter",
        "Pulse oximeter",
        "Sample design (CC0): MAX30102 pulse oximeter, KiCad 6 (legacy format)."
        " You can delete this project.",
        ("pulse-ox.kicad_sch", "pulse-ox.kicad_pro"),
    ),
    Sample(
        "ecg-patch",
        "ECG patch",
        "Sample design (CC0): wearable ECG patch as an EDIF netlist (not KiCad)."
        " You can delete this project.",
        ("ecg-patch.edf",),
    ),
    Sample(
        "thermometer",
        "Digital thermometer",
        "Sample design (CC0): thermometer given only as a PDF BOM table."
        " You can delete this project.",
        ("thermometer-bom.pdf",),
    ),
)


def load_files(sample: Sample) -> list[tuple[str, bytes]]:
    """Design files of a sample as (name, bytes)."""
    return [(name, (sample.directory / name).read_bytes()) for name in sample.files]
