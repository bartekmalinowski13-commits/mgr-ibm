# Digital thermometer

- Format: PDF BOM table (landscape A4, one table)
- Files to upload: thermometer-bom.pdf
- Reference BOM: `reference_bom.csv` (upload it in the run's evaluation panel)
- Source and licence: self-authored for this project (`tools/make_sample_pack.py`), **CC0-1.0**;
  part numbers are real catalogue parts used as test data; no third-party design is included.

NTC bridge with an OPA333 amplifier and an LP5907 supply. The NTC thermistor NCP15XH103F03RC is not in the sample datasheet corpus, so agents cannot confirm it from the knowledge base. The parser reads the table from the page layout (confidence 0.75): review the items.

Check it yourself: `uv run bomagent bom <files> --out bom.csv`, then
`uv run bomagent eval bom.csv reference_bom.csv` (the deterministic BOM is complete except for
parts that have no MPN in the source).
