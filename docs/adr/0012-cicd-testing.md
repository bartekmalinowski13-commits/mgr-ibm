# ADR-0012: CI/CD w GitHub Actions i strategia testów

Status: Zaakceptowany · 2026-11-09

## Kontekst
Wymagane testy E2E, smoke i wszystko zielone przed wydaniem.

## Decyzja
Pipeline opisany w `ARCHITECTURE.md §13` i `TESTING.md`. Trunk-based: krótkie gałęzie `feat/<moduł>-<opis>`, PR, squash merge po zielonym CI. Conventional Commits + release-please. Deploy przez OIDC, wyłączony do czasu konfiguracji AWS.

## Konsekwencje
Każda zmiana przechodzi tę samą bramkę jakości. Testy z LLM są deterministyczne (fałszywy dostawca / nagrania).

## Rozważane alternatywy
GitFlow (długie gałęzie, konflikty).
