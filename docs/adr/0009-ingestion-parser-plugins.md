# ADR-0009: Ingestia: wtyczki parserów w izolowanym workerze

Status: Zaakceptowany · 2026-11-09

## Kontekst
Wymagane formaty: KiCad, Altium, Cadence OrCAD/Allegro, PDF, DXF/DWG; część formatów jest zamknięta i binarna.

## Decyzja
Interfejs wtyczki `FormatParser` (wykrywanie, parsowanie, poziom pewności). Kolejność ścieżek: format otwarty → parser natywny; format zamknięty → parser open source po spike’u (z oceną licencji) → eksport neutralny z narzędzia klienta (IPC-2581, ODB++, EDIF, CSV BOM). Worker bez sieci, read-only, non-root, limity zasobów, skan malware przed parsowaniem.

## Konsekwencje
Bezpieczne przetwarzanie niezaufanych plików, łatwe dodawanie formatów. Uczciwość wobec klienta: UI mówi, gdy potrzebny jest eksport.

## Rozważane alternatywy
Parsowanie w procesie API (ryzyko bezpieczeństwa i stabilności).
