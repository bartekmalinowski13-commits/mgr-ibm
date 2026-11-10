# Status projektu

_Aktualizuje Claude Code po każdym kamieniu milowym (patrz `docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md` §5)._

## 2026-11-10 (rano) – po nocy

| KM | Stan | Gdzie | Kto |
|---|---|---|---|
| M0 Fundament | ✅ | gałąź `claude/code-master-prompt-part-2-5651f9` | sesja Claude Code (chmura) |
| M1 Rdzeń domeny | ✅ | ta sama gałąź | sesja Claude Code |
| M2 Baza wiedzy | ✅ | ta sama gałąź | sesja Claude Code |
| M3 Agenci A/B | ✅ | gałąź `feat/m3-agents-runtimes` (na M0–M2) | Claude z projektu (sesja stanęła po M2) |
| M4 API – część 1 (przebiegi end-to-end) | ✅ | gałąź `feat/m4-runs-api` (na M3) | Claude z projektu |
| M4 część 2 (onboarding, SSO, klucze API, metering) | ⏳ | `docs/plans/M4-runs-api.md` | – |
| M5 Frontend – część 1 (+ z M4 cz. 2: API bazy wiedzy, przegląd BOM przez człowieka) | ✅ | gałąź `feat/m5-web` (na M4) | Claude z projektu |
| M5 część 2, M6–M8 | ⏳ | `docs/plans/M5-web.md` | – |

**Frontend (`feat/m5-web`):** vitest 12/12, Playwright 21/21 (w tym axe WCAG 2.1 AA, mobile smoke), `tsc`, `biome` czyste; zrzuty w `docs/design/screens/m5/`. Uruchom: `pnpm --filter @bomagent/web dev:mock`.

**Weryfikacja (lokalnie, Postgres 16 + pgvector natywnie):** 350 testów zielonych na `feat/m5-web` (341 na `feat/m4-runs-api`) (w tym izolacja tenantów, integracyjne, kontrakt OpenAPI), pokrycie 94%, `ruff`, `mypy --strict`, `import-linter` czyste. Ścieżka dockerowa (`just up`, Testcontainers) **nie była uruchomiona** – brak demona Dockera; sprawdzi ją CI. Zamiast niej pełny stos uruchomiony natywnie (`just up-native`: Postgres + moto + fake LLM + API + 3 workery jako procesy) i przetestowany: `just e2e-stack` – 2/2 (upload KiCad przez presigned URL → parsowanie → przebiegi A i B przez SQS → porównanie → poprawka pozycji; dokument w bazie wiedzy → indeksowanie). `up-native` indeksuje też karty katalogowe z `evals/fixtures/datasheets` do wspólnego korpusu – bez tego wariant B na pustej bazie wiedzy nie ma z czego wybierać części (0% pól od agenta), z korpusem: 6 pozycji wybranych przez agenta z cytatami.

### Jak uruchomić
```bash
uv sync --all-packages
export BOMAGENT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres  # albo Docker/Testcontainers
uv run pytest -m "not smoke and not e2e"
uv run bomagent compare evals/fixtures/kicad/ecg-frontend --reference evals/fixtures/kicad/ecg-frontend/reference_bom.csv
uv run bomagent run evals/fixtures/kicad/pulse-ox --variant A --trace trace.json   # offline, symulator
# prawdziwy model: --gateway-url http://localhost:4000 --gateway-key ... --model <id z katalogu po weryfikacji>
```

### Do akceptacji
Patrz `docs/DECISIONS_LOG.md`, kolumna „Do akceptacji = tak” (m.in. moto zamiast LocalStack, pypdf zamiast PyMuPDF – licencja AGPL, wymiar embeddingów 1024, checkpointy LangGraph w M4, adapter Claude Agent SDK tylko z Bedrock UE).

### Potrzebne od człowieka
1. Scalić gałęzie do `main` po kolei (każda bazuje na poprzedniej): `claude/code-master-prompt-part-2-5651f9` (M0–M2) → `feat/m3-agents-runtimes` → `feat/m4-runs-api` → `feat/m5-web`; zobaczyć wynik CI (pierwsze uruchomienie Dockera/E2E).
2. Konto AWS (organizacja, region eu-central-1) – dopiero do M6.
3. Dostęp do modeli w UE (Bedrock EU, Azure OpenAI EU Data Zone) – włączenie modeli w `packages/py/llm/src/bomagent_llm/catalog/models.yaml` (`enabled`/`verified`) po sprawdzeniu ID w konsoli.
4. Decyzja o zbiorze ewaluacyjnym (`docs/thesis/ZBIOR_EWALUACYJNY_KANDYDACI.md` na `main`).

### Następne kroki
1. M4 część 2: onboarding organizacji, SSO per organizacja, klucze API, metering/limity, KB admin (globalny korpus – panel platformy), edycja BOM → wiedza tenanta, checkpointy LangGraph w Postgresie, klient TS.
2. M5 część 2: logowanie OIDC w UI, baza wiedzy, edycja BOM, ustawienia organizacji.
3. M6: CDK + cdk-nag.
4. M7: kolejne formaty (IPC-2581, PDF, DXF; spike’i Altium/OrCAD).
5. M8: eksperyment na prawdziwych modelach (A/B × zamknięty/otwarty × N).
