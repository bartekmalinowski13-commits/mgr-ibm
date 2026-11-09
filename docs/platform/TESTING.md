# Strategia testów

Zasada: **TDD** (skill `test-driven-development` z superpowers) – test przed kodem. CI jest bramką: nic nie trafia do `main` bez zielonego pipeline’u.

## Piramida
| Poziom | Narzędzia | Zakres | Kiedy |
|---|---|---|---|
| Statyczne | ruff, mypy --strict, import-linter, biome, tsc, cdk-nag, gitleaks | styl, typy, granice modułów, sekrety, zgodność IaC | każdy commit (pre-commit) i PR |
| Jednostkowe | pytest, Hypothesis, vitest, Testing Library | logika domenowa, normalizacja wartości, reguły, komponenty UI | PR |
| Integracyjne | pytest + Testcontainers (Postgres+pgvector), emulator S3/SQS, LiteLLM z fałszywym dostawcą | repozytoria, RLS, kolejki, workery, retrieval | PR |
| Izolacja tenantów | pytest (osobny marker `isolation`) | próby dostępu do cudzych danych przez API, SQL, S3, KB, zdarzenia | PR – **blokuje merge** |
| Kontraktowe | Schemathesis na OpenAPI; test zgodności klienta TS z kontraktem | API vs specyfikacja | PR |
| E2E | Playwright na lokalnym stosie (docker compose) z fałszywym dostawcą LLM | pełne ścieżki użytkownika w UI | PR (zestaw krytyczny), nocny (pełny) |
| Smoke | pytest + Playwright (tag `@smoke`) | czy wdrożenie działa | po każdym wdrożeniu (dev, staging, prod) i lokalnie `just smoke` |
| Ewaluacje LLM | `packages/py/eval` + `evals/` | jakość BOM vs referencja (F1, halucynacje, koszt) | nocny pipeline z prawdziwymi modelami (tylko gdy są sekrety), lokalnie na żądanie; regresja = alarm |
| Wydajnościowe | k6 | API p95, przepustowość kolejki | nocny na stagingu |
| Bezpieczeństwa | CodeQL, Trivy, OWASP ZAP baseline | podatności | PR / nocny |
| Infrastruktura | `aws-cdk-lib/assertions`, snapshoty, cdk-nag | stacki CDK | PR |

## Deterministyczność testów z LLM
- W CI dostawca LLM = **fałszywy model** w LiteLLM (odpowiedzi z nagrań w `tests/cassettes/` dopasowywane po haszu promptu) – testy nie zależą od sieci ani od kosztów.
- Testy jakości modeli to **ewaluacje**, nie testy jednostkowe – raportują metryki, nie „pass/fail” na pojedynczym przykładzie (poza progami regresji).

## Testy smoke (minimalny zestaw, musi przejść po każdym wdrożeniu)
1. `GET /healthz` i `/readyz` dla każdego serwisu (w tym gateway).
2. Logowanie użytkownika testowego tenanta `smoke-a` (lokalnie: konto lokalne; w chmurze: dedykowany użytkownik).
3. Upload przykładowego projektu KiCad → status `parsed`.
4. Uruchomienie przebiegu wariantu B (fałszywy LLM lokalnie / najtańszy model w chmurze) → status `completed`, BOM ma > 0 pozycji.
5. Eksport CSV zwraca plik.
6. Istnieje zdarzenie audytowe dla przebiegu.
7. Użytkownik tenanta `smoke-b` dostaje 404 przy próbie odczytu przebiegu `smoke-a`.
8. Trace przebiegu jest widoczny w kolektorze OTel (lokalnie: zapytanie do Tempo).

## Scenariusze E2E (Playwright)
- Rejestracja organizacji → zaproszenie członka → przełączanie organizacji.
- Nowy przebieg z szablonu (modal z wyborem wariantu) → podgląd postępu na żywo → przegląd BOM → panel pochodzenia pozycji → akceptacja/poprawka pozycji (zapis jako wiedza tenanta) → eksport.
- Porównanie wariantów A i B na tym samym projekcie.
- Admin: konfiguracja SSO (formularz), role, limity, log audytu z filtrowaniem.
- Dostępność: `@axe-core/playwright` na każdej stronie (brak naruszeń WCAG 2.2 AA).

## Progi
Pokrycie: ≥ 85% dla `packages/py/*` (rdzeń domeny), ≥ 75% dla serwisów i frontendu; brak spadku pokrycia w PR. Zero naruszeń axe. Zero krytycznych/wysokich podatności bez wyjątku z uzasadnieniem.
