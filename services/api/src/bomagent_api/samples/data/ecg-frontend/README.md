# ECG front-end

- Format: KiCad 8, hierarchical (root + AFE + power sheets)
- Files to upload: ecg-frontend.kicad_sch, afe.kicad_sch, power.kicad_sch, ecg-frontend.kicad_pro
- Reference BOM: `reference_bom.csv` (upload it in the run's evaluation panel)
- Source and licence: self-authored for this project (`tools/make_sample_pack.py`), **CC0-1.0**;
  part numbers are real catalogue parts used as test data; no third-party design is included.

3-lead ECG analog front end: INA333 + OPA333, ESD protection, MCP1700 regulator, battery connector. R9 is DNP; several resistors and capacitors have no MPN in the schematic (the reference BOM has them, plus alternates for 100n and 100k).

Check it yourself: `uv run bomagent bom <files> --out bom.csv`, then
`uv run bomagent eval bom.csv reference_bom.csv` (the deterministic BOM is complete except for
parts that have no MPN in the source).
