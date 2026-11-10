# bomagent-cad-parsers (`bomagent_cad`)

**Responsibility:** turn untrusted design files into `ParsedDesign` (FORMATS.md, ADR-0009).
Runs inside the sandboxed `ingest-worker`.

## Public interface
- `FileRef(name, data)`, `FormatParser` protocol: `format_id`, `version`, `sniff(file) -> 0..1`, `parse(files) -> ParsedDesign`
- `parse_files(files)`, `detect(files)`; `ParseError` / `UnsupportedFormatError` carry a `code` for the UI i18n catalogue (`kicad.legacy`, `unsupported.allegro_brd`, ...)

| Plugin | Formats | Notes |
|---|---|---|
| `kicad.KicadParser` | KiCad 6-9 `.kicad_sch` (+ `.kicad_pro`, optional `.kicad_pcb`) | hierarchical sheets incl. a sheet used several times, KiCad 6 `symbol_instances`, multi-unit symbols, `in_bom`/`dnp` flags and `DNP` field, PCB footprint cross-check; KiCad 5 `.sch` rejected with a conversion hint |
| `ipc2581.Ipc2581Parser` | IPC-2581 rev B/C `.xml`/`.cvg` | `defusedxml` (DTD/entities refused), namespace-agnostic; BOM items + AVL (MPN, manufacturer, chosen/best-ranked part) + placements; without a BOM section: placements only, confidence 0.6 |
| `edif.EdifParser` | EDIF 2.0.0 `.edf`/`.edif`/`.edn` | bounded S-expression reader; `rename` for designators, properties to value/footprint/MPN/manufacturer/DNP (others kept as fields), nets from `portRef`; `%nn%` escapes decoded |
| `odbpp.OdbppParser` | ODB++ job `.tgz`/`.tar.gz`/`.zip` | read in memory under limits (decompressed total, entries), absolute paths / `..` / links reject the archive; `comp_+_top|bot/components` (`CMP` + `PRP` records) and package names from `eda/data`; `.Z`-compressed members reported |
| `csv_bom.CsvBomParser` | CSV/TSV BOM | header aliases, `,`/`;`/tab, preambles, ranges `R1-R4`, Qty mismatch and duplicates reported as limitations |

Unsupported formats (Allegro `.brd`, Altium, OrCAD, DWG, XLSX) produce an actionable hint
instead of a guess (M7 next: DXF, PDF BOM - `docs/plans/M7-formats.md`).

## Safety
`sexpr.parse` is iterative with limits on size (64 MB), depth (512) and token count; no
recursion on file content; UTF-8 decoding is strict; files are never executed.

## Testing
`uv run pytest packages/py/cad-parsers` - fixture projects in `evals/fixtures/kicad/`
(regenerate with `uv run python tools/fixtures/gen_kicad_fixtures.py evals/fixtures/kicad`),
robustness cases (truncated, nesting bomb, binary, legacy, recursive sheets, XXE and
entity expansion). IPC-2581, EDIF and ODB++ fixtures (`evals/fixtures/{ipc2581,edif,odbpp}/`)
are generated from the KiCad fixtures by `uv run python tools/make_format_fixtures.py`;
the tests require each to parse into exactly the KiCad parts (cross-format consistency).
