# Sample design pack

Five small, realistic biomedical designs for trying the whole flow: upload, parse, run A/B,
BOM, correction, export, compare, evaluation against a reference.

This directory is `evals/samples/` (a symlink) and is also what the API adds to new
organisations as `[Sample] ...` projects (`services/api`, `bomagent_api.samples`).
Everything here is **self-authored and released under CC0-1.0** (no third-party design is
copied); part numbers are real catalogue parts used as test data (facts, not copyrighted
content). Rebuild with `uv run python tools/make_sample_pack.py`.

| Sample (folder) | Project name in the app | Format | Lines (parts) | Demonstrates |
|---|---|---|---|---|
| `ecg-frontend/` | `[Sample] ECG front-end` | KiCad 8, 3 hierarchical sheets | 21 (30 parts) | hierarchy, DNP part (R9), power symbols, parts without MPN that agents must complete, accepted alternates |
| `eeg-2ch/` | `[Sample] EEG 2-channel` | KiCad 9, one sheet used twice | 10 (19 parts) | repeated sheet instances (U101/U201), multi-unit op-amp, DNP crystal |
| `pulse-oximeter/` | `[Sample] Pulse oximeter` | KiCad 6 (legacy `symbol_instances`) | 9 (11 parts) | oldest format, DNP stored as a field, optical sensor module |
| `ecg-patch/` | `[Sample] ECG patch` | EDIF 2.0.0 netlist (non-KiCad) | 15 (18 parts) | netlist-only input, 0402 passives, ESD diodes, DNP jumper |
| `thermometer/` | `[Sample] Digital thermometer` | PDF BOM table | 10 (13 parts) | tabular input (confidence below 1.0 by design), an NTC thermistor missing from the sample knowledge base |

Each folder holds the design file(s), `reference_bom.csv` (the ground truth used for the
evaluation step) and a `README.md`. Only the design files are uploaded; the reference BOM is
what you upload in the run's evaluation panel.

The reference BOMs come from the generator's part list and were cross-checked with the
deterministic pipeline (`uv run bomagent parse|bom|eval`): line F1 is 0.95 to 1.00 for every
sample, the difference being lines the schematic leaves without an MPN (the work left for
the agents). `services/api/tests/test_samples.py` asserts this on every CI run.

Manufacturer datasheets are not included. The synthetic datasheet corpus in
`evals/fixtures/datasheets/` covers the MPNs used here (except the NTC thermistor, on purpose).
