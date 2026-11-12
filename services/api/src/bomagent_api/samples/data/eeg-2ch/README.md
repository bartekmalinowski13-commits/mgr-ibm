# EEG 2-channel

- Format: KiCad 9, one channel sheet instantiated twice
- Files to upload: eeg-2ch.kicad_sch, channel.kicad_sch, eeg-2ch.kicad_pro
- Reference BOM: `reference_bom.csv` (upload it in the run's evaluation panel)
- Source and licence: self-authored for this project (`tools/make_sample_pack.py`), **CC0-1.0**;
  part numbers are real catalogue parts used as test data; no third-party design is included.

Two-channel EEG board around the ADS1292R with INA333 + OPA2333 per channel. Tests designator remapping (U101 and U201) and a multi-unit part. Y1 is DNP.

Check it yourself: `uv run bomagent bom <files> --out bom.csv`, then
`uv run bomagent eval bom.csv reference_bom.csv` (the deterministic BOM is complete except for
parts that have no MPN in the source).
