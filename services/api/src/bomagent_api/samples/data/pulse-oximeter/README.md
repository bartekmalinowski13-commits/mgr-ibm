# Pulse oximeter

- Format: KiCad 6 (root symbol_instances, DNP as a field)
- Files to upload: pulse-ox.kicad_sch, pulse-ox.kicad_pro
- Reference BOM: `reference_bom.csv` (upload it in the run's evaluation panel)
- Source and licence: self-authored for this project (`tools/make_sample_pack.py`), **CC0-1.0**;
  part numbers are real catalogue parts used as test data; no third-party design is included.

MAX30102 SpO2 / heart-rate module with LP5907 + MCP1700 supplies and I2C pull-ups. R3 is DNP (field style), the smallest sample.

Check it yourself: `uv run bomagent bom <files> --out bom.csv`, then
`uv run bomagent eval bom.csv reference_bom.csv` (the deterministic BOM is complete except for
parts that have no MPN in the source).
