# ADR-0001: Monorepo i modułowe serwisy zamiast monolitu lub drobnych mikroserwisów

Status: Zaakceptowany · 2026-11-09

## Kontekst
Projekt ma być modułowy (nie monolit), ale jest rozwijany przez jedną osobę i agentów AI, a część kodu musi być współdzielona przez warianty A i B eksperymentu.

## Decyzja
Jedno monorepo (`uv` workspace + `pnpm` workspace). Kod domenowy w bibliotekach `packages/py/*` z granicami pilnowanymi przez `import-linter`. Cztery serwisy wdrożeniowe: `api`, `ingest-worker`, `agent-worker`, `kb-indexer` + gotowe komponenty (`llm-gateway`, Langfuse, opcjonalnie `model-serving`). Nowy serwis tylko, gdy ma inny profil bezpieczeństwa, skalowania albo cyklu wydań – uzasadnienie w nowym ADR.

## Konsekwencje
Atomowe zmiany przekrojowe, jeden pipeline CI, wspólne narzędzia. Ryzyko: rozrost CI – łagodzone filtrami ścieżek (`paths`) i budowaniem tylko zmienionych pakietów.

## Rozważane alternatywy
Polirepo (narzut koordynacji wersji); pełne mikroserwisy per domena (narzut sieci, transakcji rozproszonych i operacji bez korzyści na tym etapie).
