# M7 - More input formats

Source: `docs/platform/FORMATS.md`, ADR-0009 (parsers in the sandboxed ingest worker).
Principle from FORMATS.md: never pretend to parse what we do not parse - every parser
returns `confidence` and `limitations`, and the UI shows them.

## Order (open, structured formats first)

| Step | Format | Approach | Status |
|---|---|---|---|
| 1 | IPC-2581 (`.xml`, `.cvg`) | `defusedxml` (no DTD, no entities - XXE safe), namespace-agnostic; BOM section (`BomItem`/`RefDes`/`Characteristics`) + approved vendor list (`Avl`) for MPN/manufacturer; fallback to `Ecad/.../Component` placements with a limitation | done |
| 1 | EDIF 2.0 (`.edf`, `.edif`, `.edn`) | existing bounded S-expression reader; instances with `rename`, properties (value, footprint, MPN, manufacturer), nets from `joined/portRef` | done |
| 2 | ODB++ (`.tgz`, `.zip`) | archive read in memory with limits (entries, total size, ratio - zip bomb), no extraction to disk, path traversal rejected; `steps/*/layers/comp_+_top|bot/components` | done |
| 2 | DXF (`.dxf`) | `ezdxf` (MIT): BOM tables (TABLE entities, text grids) and block attributes (mechanical BOM) | next |
| 3 | PDF BOM (`.pdf`) | table extraction (pypdf text layout first; Docling optional in the kb-indexer image) - low confidence, items flagged for review | later |

Not in M7: Altium/OrCAD native binaries and DWG (licence and maturity spikes, ADR first) -
the registry keeps returning an honest "export IPC-2581 / EDIF / CSV" hint for them.

## Tests (TDD)

- Fixtures are generated from the open KiCad fixtures by `tools/make_format_fixtures.py`
  (self-authored, same licence as the KiCad fixtures), so every new format has a
  **cross-format consistency test**: the parsed components (refdes, value, footprint,
  MPN, manufacturer, DNP) equal the KiCad parse of the same design.
- Robustness: XXE / billion laughs rejected, oversize input, malformed structure ->
  `ParseError` with a stable code, never a crash; sniffing does not misfire on other XML.
- The experiment and API need no change: `parse_files` picks the parser by `sniff`.

## Done when

Parsers registered, fixtures + consistency and robustness tests green, `FORMATS.md`
status column and the module README updated, UI hints for still-unsupported formats
unchanged, `docs/STATUS.md` updated.
