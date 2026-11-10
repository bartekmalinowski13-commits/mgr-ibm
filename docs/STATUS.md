# Status projektu

_Aktualizuje Claude Code po każdym kamieniu milowym (patrz `docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md` §5)._

## 2026-11-10 – stan po sesji nocnej (gałąź `claude/code-master-prompt-part-2-5651f9`)

> **Gdzie jest kod:** cała praca jest na gałęzi `claude/code-master-prompt-part-2-5651f9` (środowisko sesji pozwalało wypychać tylko tam – patrz `docs/DECISIONS_LOG.md`). **Nic nie jest scalone do `main`.** Do review: PR z tej gałęzi do `main` (squash) – commity są podzielone per kamień milowy.

### Co jest gotowe

| KM | Zakres | Commit | Stan |
|---|---|---|---|
| M0 | monorepo (uv 15 pakietów + pnpm/biome), justfile, pre-commit, ruff/mypy --strict/import-linter, `platform-common` (kontekst tenanta, RLS, audyt z łańcuchem skrótów, OTel, structlog z redakcją, problem+json, kolejki SQS z kontekstem tenanta/śladu, magazyn S3 z prefiksem tenanta), migracja 0001 (role bez BYPASSRLS, tenants, audit), szkielety 4 serwisów z `/healthz` `/readyz`, `deploy/compose` (Postgres+pgvector, moto, LiteLLM + fake LLM, otel-lgtm, Langfuse, Ollama), GitHub Actions (przypięte SHA), Dependabot, szablony | `88211a8`, poprawki po review `158a34c` | ✅ (ścieżka dockerowa nieuruchomiona lokalnie – patrz niżej) |
| M1 | `bom-core` (model z pochodzeniem per pole, normalizacja wartości/jednostek, obudowy, grupowanie, eksport CSV/JSON, JSON Schema), `cad-parsers` (KiCad 6–9 + CSV BOM, podpowiedzi dla formatów nieobsługiwanych), `rules` core@1.0.0 (w tym flagi IEC 60601), `eval` (P/R/F1, dokładność pól, pokrycie i halucynacje MPN, wstrzykiwanie błędów, powtarzalność), CLI `bomagent parse|bom|eval`, 3 fixture'y KiCad (CC0) | `1d5d335`, poprawki po review `06f838f` | ✅ |
| M2 | `llm` (katalog modeli EU closed/open-weight z bramką weryfikacji, embeddingi gateway/hashing), migracja 0002 (`kb.*` z RLS global/tenant), `kb` (ekstrakcja PDF, chunking, hybryda pgvector+FTS+RRF+reranker, snapshoty, korekty jako wiedza tenanta, flagowanie prompt injection), `kb-indexer` (handler SQS), 18 syntetycznych datasheetów + zestaw zapytań | `4e21c4d` | ✅ |
| M3 | agenci A/B | – | ⏳ w toku (patrz „Następne kroki”) |
| M4–M8 | API SaaS, frontend, CDK, formaty, eksperyment | – | ❌ nie rozpoczęte |

Plany i brainstorming: `docs/plans/M0-foundation.md`, `M1-domain-core.md`, `M2-knowledge-base.md`.

### Jak uruchomić

```bash
just bootstrap                       # uv sync --all-packages + pnpm install + pre-commit
# testy z bazą: Postgres 16 + pgvector; albo Docker (Testcontainers), albo:
export BOMAGENT_TEST_DATABASE_URL=postgresql+psycopg://postgres:<hasło>@localhost:5432/postgres
just test                            # unit + integracyjne + izolacji, z pokryciem
just test-isolation                  # tylko testy izolacji tenantów (blokujące w CI)
just lint                            # ruff, mypy --strict, import-linter, biome
uv run bomagent parse evals/fixtures/kicad/ecg-frontend --summary
uv run bomagent bom evals/fixtures/kicad/ecg-frontend --format json --out /tmp/bom.json
uv run bomagent eval /tmp/bom.json evals/fixtures/kicad/ecg-frontend/reference_bom.csv
just up && just smoke                # pełny stos dockerowy (niezweryfikowane lokalnie)
```

### Wyniki testów (2026-11-10, lokalnie, Python 3.13, PostgreSQL 16.15 + pgvector 0.6)
- **340 testów zielonych** (unit + integracyjne + izolacji), 6 pominiętych z założenia (smoke/e2e – wymagają działającego stosu).
- Pokrycie: `packages/py/*` **97,3 %** (próg 85 %), serwisy **82,6 %** (próg 75 %).
- ruff, ruff format, mypy --strict (69 plików), import-linter (2 kontrakty) – czyste.
- Retrieval (M2) na syntetycznym korpusie: recall@5 = 1,00, recall@1 = 0,89 (18 zapytań).
- Smoke natywnie (serwisy uruchomione bez Dockera): `/healthz` + `/readyz` z bazą dla 4 serwisów – zielone.
- Review subagentem po M0 i M1 – wszystkie uwagi wysokiej wagi naprawione (commity `158a34c`, `06f838f`).

### Czego nie zrobiono / znane ograniczenia
- **Docker niedostępny w sesji:** `just up`, `just smoke` (trace w Tempo), Testcontainers i obrazy nie zostały uruchomione lokalnie – sprawdzi je CI (`pr.yml`, job `stack-smoke`). Serwis `fake-llm` w compose powstaje w M3 – do tego czasu `stack-smoke` w CI będzie czerwony.
- **CI nie zostało jeszcze obejrzane** na GitHubie (workflow uruchamia się na push do `claude/**`).
- Pluginy **superpowers / frontend-design** niedostępne w sesji – proces prowadzony ręcznie (brainstorm → plan w `docs/plans` → TDD → review subagentem → weryfikacja).
- `kicad-cli` (weryfikacja krzyżowa parsera) niedostępny – parser testowany na własnych fixture'ach.
- Pakiet reguł `core@1.0.0` zmienił się w poprawkach po review, ale nie był jeszcze użyty w żadnym eksperymencie – wersja nie została podbita.

### Decyzje do Twojej akceptacji (pełna lista: `docs/DECISIONS_LOG.md`)
1. Praca na gałęzi sesji zamiast `feat/*` + brak scalania do `main`.
2. moto (Apache-2.0) jako emulator S3/SQS zamiast LocalStack (wymaga konta od 03.2026).
3. ADR-0016: jeden pakiet migracji z ręcznym DDL i 3 rolami bazy.
4. pypdf zamiast PyMuPDF (AGPL), Docling opcjonalnie.
5. `vector(1024)`; modele w katalogu wyłączone do czasu ręcznej weryfikacji dostępności w regionie UE.
6. Definicje metryk do pracy (halucynacja = MPN spoza katalogu; dokładność pól liczona na wszystkich pozycjach referencji) – `packages/py/eval/README.md`.

### Czego potrzebuję od Ciebie (wg ważności)
1. Review i scalenie gałęzi do `main` (PR), włączenie ochrony gałęzi z wymaganym checkiem `tenant isolation (blocking)`.
2. Do eksperymentu (M8): wybór otwartych projektów biomedycznych KiCad z licencją i ręczne BOM-y referencyjne; datasheety do korpusu globalnego (nie commitujemy ich – prawa autorskie).
3. Konta i klucze (dopiero dla przebiegów na prawdziwych modelach): AWS (Bedrock w `eu-central-1`, profile EU), Azure OpenAI (Data Zone EU), opcjonalnie Mistral – ID modeli wpisuje się w `packages/py/llm/src/bomagent_llm/catalog/models.yaml` i ustawia `enabled/verified`.
4. Decyzja o koncie AWS / Organizations przed M6 (CDK).

### Następne kroki (dla kolejnej sesji: „kontynuuj”)
1. **M3:** `bomagent_llm` – klient chat/structured output przez gateway, fałszywy dostawca z nagraniami (`tests/cassettes`, serwer `bomagent_llm.fake_server` dla compose); `bomagent_agents` – wersjonowane prompty, `VariantRuntime`, `langgraph_b` (deterministyczny potok + agent doboru MPN z RAG dla pozycji nierozstrzygniętych + walidacja/naprawa), `langgraph_a` (100 % LLM), `claude_agent_sdk_a` (adapter), budżety, fan-out, checkpointy Postgres; `agent-worker` (SQS); CLI `bomagent run --variant A|B`.
2. Obejrzeć pierwszy przebieg CI na GitHubie i naprawić ewentualne błędy (Testcontainers, compose).
3. M4: API (tenancy, OIDC + lokalny mock IdP, RBAC, projekty, przebiegi + SSE, BOM, audyt), OpenAPI 3.1 + klient TS, testy kontraktowe.
4. M5: frontend wg `docs/design/UX_GUIDELINES.md`.
5. M6–M8: CDK + cdk-nag, kolejne formaty, eksperyment `bomagent experiment run`.

## 2026-11-09 – stan wyjściowy
- Gotowe: szablon pracy (DOCX), struktura pracy, diagram wariantów A/B, prototyp przepływu UI (HTML), architektura produkcyjna, 15 ADR, wytyczne UX, roadmapa M0–M8, prompt dla Claude Code.
- Kodu aplikacji jeszcze nie ma – start od M0.
