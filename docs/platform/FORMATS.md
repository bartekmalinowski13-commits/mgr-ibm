# Supported input formats

Principle: **we do not pretend to parse something we do not parse.** Every parser returns a `ParsedDesign` with a `confidence` field and a list of `limitations`, and the UI shows the user what is missing and which export would improve the result.

Interpretive assumption: "Guidance" from the requirements = **Cadence** (OrCAD Capture / Allegro PCB).

| Format | Extensions | v1 path | What we extract | Notes and risks |
|---|---|---|---|---|
| KiCad 6–9 | `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`, netlist | S-expression parser (custom or open-source library) + `kicad-cli` (`sch export bom/netlist`) as verification | symbols, fields (Reference, Value, Footprint, MPN, Manufacturer, DNP), hierarchical sheets, netlist, footprints from the PCB | open format – priority M1, basis of the thesis experiment |
| Altium Designer | `.SchDoc`, `.PcbDoc`, `.PrjPcb` | spike: OLE structure parser (open-source libraries, licence assessment); fallback: BOM CSV export / netlist / IPC-2581 / ODB++ | components and parameters from the schematic | closed binary format; the spike result goes in an ADR |
| Cadence OrCAD Capture | `.DSN`, `.OLB` | spike: open-source parser (e.g. projects from the OpenOrCadParser family – assessment of maturity and licence); fallback: netlist (Allegro/Telesis), EDIF, BOM from CIS | components, part properties | closed format |
| Cadence Allegro PCB | `.brd` | **neutral export**: IPC-2581 (Allegro exports it natively), ODB++, ASCII reports (extracta) | footprints, refdes, placement | no reliable open `.brd` parser – message in the UI |
| IPC-2581 | `.xml`, `.cvg` | XML parser (IPC-2581 schema) | BOM, components, footprints | open format, recommended export for all tools |
| ODB++ | `.tgz` | directory structure parser | components, footprints | open specification |
| EDIF | `.edf`, `.edif` | S-expression parser | netlist, instances | neutral netlist format |
| PDF – schematics | `.pdf` | vector text (PyMuPDF), for rasters OCR + vision model | refdes, values, designators | lower confidence; items marked for review |
| PDF – BOM / datasheets | `.pdf` | table extraction (Docling / pdfplumber) | BOM tables, component parameters for the KB | datasheets feed the knowledge base |
| DXF | `.dxf` | `ezdxf` | BOM tables / title blocks, blocks with attributes (mechanical enclosure parts) | mechanical BOM, complements the electronic one |
| DWG | `.dwg` | conversion to DXF in an isolated container (ODA File Converter – licence to be checked, or LibreDWG – GPLv3, legal assessment for SaaS), then as DXF | as DXF | ADR after the licence assessment |
| CSV/XLSX BOM | `.csv`, `.xlsx` | column mapping with preview | BOM items | import of reference BOMs and existing bills of materials |

## Implementation status

| Format | Status | Parser |
|---|---|---|
| KiCad 6-9 | done (M1) | `bomagent_cad.kicad` |
| CSV BOM | done (M1) | `bomagent_cad.csv_bom` |
| IPC-2581 rev B/C | done (M7) | `bomagent_cad.ipc2581` |
| EDIF 2.0.0 | done (M7) | `bomagent_cad.edif` |
| ODB++ (`.tgz`, `.zip`) | done (M7) | `bomagent_cad.odbpp` |
| DXF parts lists (block attributes, exploded tables) | done (M7) | `bomagent_cad.dxf` |
| PDF BOM tables (text layer) | done (M7) | `bomagent_cad.pdf_bom` |
| PDF schematics, scanned PDFs (OCR / vision model) | planned after v1 | - |
| Altium, OrCAD native, Allegro `.brd`, DWG, XLSX | not parsed - the upload returns an export hint | - |

## Plugin contract
```python
class FormatParser(Protocol):
    format_id: str                       # e.g. "kicad", "ipc2581"
    def sniff(self, file: FileRef) -> float: ...          # 0..1, whether this is that format
    def parse(self, files: list[FileRef]) -> ParsedDesign: ...
```
`ParsedDesign`: components (refdes, value, footprint, fields, DNP), nets (optional), sheets, `source_format`, `confidence`, `limitations[]`, checksums of the input files.

## Tests
For each format: a set of reference files in `evals/fixtures/<format>/` (open licences!) with the expected `ParsedDesign` (snapshot), property-based tests for value normalization (e.g. `4k7` = `4.7 kΩ`), robustness tests (corrupted, huge, malicious files – zip bomb, XXE in XML).
