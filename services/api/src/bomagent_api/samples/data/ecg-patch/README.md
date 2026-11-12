# ECG patch

- Format: EDIF 2.0.0 netlist, exported by the generator (not a KiCad project)
- Files to upload: ecg-patch.edf
- Reference BOM: `reference_bom.csv` (upload it in the run's evaluation panel)
- Source and licence: self-authored for this project (`tools/make_sample_pack.py`), **CC0-1.0**;
  part numbers are real catalogue parts used as test data; no third-party design is included.

Single-lead wearable ECG patch around the AD8232 with 0402 resistors, two ESD diodes, MCP1700 regulator and JST connectors. R6 is DNP.

Check it yourself: `uv run bomagent bom <files> --out bom.csv`, then
`uv run bomagent eval bom.csv reference_bom.csv` (the deterministic BOM is complete except for
parts that have no MPN in the source).
