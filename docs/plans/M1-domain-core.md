# M1 – Rdzeń domeny (plan)

Źródła: ROADMAP M1, FORMATS.md, ARCHITEKTURA_WARIANTOW.md, STRUKTURA_PRACY.md (metryki).

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Gdzie żyje `ParsedDesign`? | `bom-core` | wspólny kontrakt wejścia runtime'ów A/B (ADR-0007); parsery tylko go produkują |
| Pochodzenie na poziomie pozycji czy pola? | per pole (`provenance: {field: Provenance}`) | UI „panel pochodzenia” i audyt muszą wiedzieć, kto ustalił MPN, a kto ilość |
| Własny parser S-expr czy biblioteka? | własny, iteracyjny, z limitami | pliki niezaufane (SECURITY.md); zero zależności w workerze-sandboxie |
| Skąd fixture'y KiCad? | własne, generowane skryptem, CC0 | brak ryzyka licencyjnego; projekty open source do M8 wybiera człowiek |
| Jak liczyć dokładność MPN, skoro rezystor 10k 0603 ma wiele poprawnych MPN? | referencyjny BOM ma kolumnę `MPN Alternates` | uczciwa ocena wariantów |
| Jak definiować halucynację MPN? | MPN nieobecny w żadnym zaufanym źródle (referencja, alternatywy, projekt, katalog KB) | mierzalne bez dostępu do sieci; katalog z KB w M2 |
| IEC 60601 – werdykt czy flaga? | flaga `review` dla człowieka | narzędzie wspiera, nie zastępuje akt ryzyka (SECURITY.md – pozycja regulacyjna) |

## Zadania (TDD) i stan
1. `bom-core`: model, wartości/jednostki (+Hypothesis), refdes, obudowy, grupowanie, eksport CSV/JSON, JSON Schema – ✅
2. `cad-parsers`: S-expr, KiCad 6–9 (+PCB), CSV BOM, rejestr + podpowiedzi dla nieobsługiwanych formatów – ✅
3. Fixture'y: 3 projekty + referencyjne BOM-y + `SOURCES.md` – ✅
4. `rules` `core@1.0.0` – ✅
5. `eval`: metryki, wstrzykiwanie błędów, agregacja, raporty – ✅
6. CLI `bomagent parse|bom|eval` – ✅

## Kryteria akceptacji
Pokrycie ≥ 85% (`packages/py/*`: 97,8%); parser KiCad przechodzi fixture'y; `bomagent parse` i `bomagent eval` działają (testy CLI).
`kicad-cli` jako weryfikacja krzyżowa – niedostępny w sesji (brak KiCad), odnotowane w STATUS.
