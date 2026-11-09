# bomagent-bom-core (`bomagent_bom`)

**Responsibility:** the BOM domain model shared by variants A and B - pure Python, no I/O
(import-linter contract "Domain model is pure").

## Public interface
| Module | What |
|---|---|
| `model` | `Component`, `ParsedDesign` (parser output), `Requirements` (applied part BF/CF, defibrillation, power source), `BomItem` with per-field `Provenance` (parser / rule + pack version / agent + model + prompt version + KB citations / user), `Finding`, `Usage`, `BomVersion` |
| `values` | `parse_value()`, `normalize_value()`, `values_equivalent()` - `4k7` = `4.7 kΩ`, `100n/50V` (voltage), `0,1µF` (decimal comma), `R47`; `Decimal`, round-trip safe |
| `refdes` | natural sort, kind from prefix (`R` resistor, `FB` ferrite bead...), `compress()` ranges |
| `packages` | package from KiCad footprints (`R_0603_1608Metric` -> `0603`), from passive MPN series (Yageo RC, Murata GRM, Samsung CL, TDK C, Panasonic ERJ, Vishay CRCW, KEMET C) and from free text |
| `grouping` | `group_components()` - deterministic normalisation + grouping (variant B core) |
| `export` | `to_csv()` (formula-injection safe), `to_json()` |
| `schema` | JSON Schema 2020-12 of the BOM; committed in `schemas/bom.schema.json` (thesis appendix B) |

## Testing
`uv run pytest packages/py/bom-core` - includes Hypothesis property tests (format/parse
round trip, RKM ≡ decimal notation) and a check that the committed JSON Schema is current
(`uv run python -m bomagent_bom.schema > packages/py/bom-core/schemas/bom.schema.json`).
