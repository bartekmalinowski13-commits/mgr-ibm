# Obsługiwane formaty wejściowe

Zasada: **nie udajemy, że parsujemy coś, czego nie parsujemy.** Każdy parser zwraca `ParsedDesign` z polem `confidence` i listą `limitations`, a UI pokazuje użytkownikowi, czego brakuje i jaki eksport poprawi wynik.

Założenie interpretacyjne: „Guidance” z wymagań = **Cadence** (OrCAD Capture / Allegro PCB).

| Format | Rozszerzenia | Ścieżka v1 | Co wyciągamy | Uwagi i ryzyka |
|---|---|---|---|---|
| KiCad 6–9 | `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`, netlista | parser S-expression (własny lub biblioteka open source) + `kicad-cli` (`sch export bom/netlist`) jako weryfikacja | symbole, pola (Reference, Value, Footprint, MPN, Manufacturer, DNP), arkusze hierarchiczne, netlista, footprinty z PCB | format otwarty – priorytet M1, baza eksperymentu pracy |
| Altium Designer | `.SchDoc`, `.PcbDoc`, `.PrjPcb` | spike: parser struktury OLE (biblioteki open source, ocena licencji); fallback: eksport BOM CSV / netlista / IPC-2581 / ODB++ | komponenty i parametry ze schematu | format zamknięty binarny; w ADR wynik spike’u |
| Cadence OrCAD Capture | `.DSN`, `.OLB` | spike: parser open source (np. projekty z rodziny OpenOrCadParser – ocena dojrzałości i licencji); fallback: netlista (Allegro/Telesis), EDIF, BOM z CIS | komponenty, właściwości części | format zamknięty |
| Cadence Allegro PCB | `.brd` | **eksport neutralny**: IPC-2581 (Allegro eksportuje natywnie), ODB++, raporty ASCII (extracta) | footprinty, refdesy, rozmieszczenie | brak wiarygodnego otwartego parsera `.brd` – komunikat w UI |
| IPC-2581 | `.xml`, `.cvg` | parser XML (schemat IPC-2581) | BOM, komponenty, footprinty | format otwarty, rekomendowany eksport dla wszystkich narzędzi |
| ODB++ | `.tgz` | parser struktury katalogów | komponenty, footprinty | otwarta specyfikacja |
| EDIF | `.edf`, `.edif` | parser S-expression | netlista, instancje | neutralny format netlist |
| PDF – schematy | `.pdf` | tekst wektorowy (PyMuPDF), dla rastrów OCR + model wizyjny | refdesy, wartości, oznaczenia | niższa pewność; pozycje oznaczane do przeglądu |
| PDF – BOM / datasheety | `.pdf` | ekstrakcja tabel (Docling / pdfplumber) | tabele BOM, parametry komponentów do KB | datasheety zasilają bazę wiedzy |
| DXF | `.dxf` | `ezdxf` | tabele BOM / tabliczki rysunkowe, bloki z atrybutami (części mechaniczne obudowy) | BOM mechaniczny, uzupełnia elektroniczny |
| DWG | `.dwg` | konwersja do DXF w izolowanym kontenerze (ODA File Converter – licencja do sprawdzenia, lub LibreDWG – GPLv3, ocena prawna dla SaaS), dalej jak DXF | jak DXF | ADR po ocenie licencji |
| CSV/XLSX BOM | `.csv`, `.xlsx` | mapowanie kolumn z podglądem | pozycje BOM | import BOM referencyjnych i istniejących zestawień |

## Implementation status

| Format | Status | Parser |
|---|---|---|
| KiCad 6-9 | done (M1) | `bomagent_cad.kicad` |
| CSV BOM | done (M1) | `bomagent_cad.csv_bom` |
| IPC-2581 rev B/C | done (M7) | `bomagent_cad.ipc2581` |
| EDIF 2.0.0 | done (M7) | `bomagent_cad.edif` |
| ODB++ (`.tgz`, `.zip`) | done (M7) | `bomagent_cad.odbpp` |
| DXF parts lists (block attributes, exploded tables) | done (M7) | `bomagent_cad.dxf` |
| PDF BOM | planned (M7, `docs/plans/M7-formats.md`) | - |
| Altium, OrCAD native, Allegro `.brd`, DWG, XLSX | not parsed - the upload returns an export hint | - |

## Kontrakt wtyczki
```python
class FormatParser(Protocol):
    format_id: str                       # np. "kicad", "ipc2581"
    def sniff(self, file: FileRef) -> float: ...          # 0..1, czy to ten format
    def parse(self, files: list[FileRef]) -> ParsedDesign: ...
```
`ParsedDesign`: komponenty (refdes, wartość, footprint, pola, DNP), sieci (opcjonalnie), arkusze, `source_format`, `confidence`, `limitations[]`, sumy kontrolne plików wejściowych.

## Testy
Dla każdego formatu: zestaw plików wzorcowych w `evals/fixtures/<format>/` (licencje otwarte!) z oczekiwanym `ParsedDesign` (snapshot), testy property-based dla normalizacji wartości (np. `4k7` = `4.7 kΩ`), testy odporności (pliki uszkodzone, ogromne, złośliwe – zip bomb, XXE w XML).
