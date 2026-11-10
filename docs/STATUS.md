# Status projektu

_Aktualizuje Claude Code po każdym kamieniu milowym (patrz `docs/prompts/CLAUDE_CODE_MASTER_PROMPT.md` §5)._

## 2026-11-10 – stan: M0–M4 gotowe (bez SSO), M5 – pierwsza część (gałąź `claude/code-master-prompt-part-2-5651f9`)

> **Gdzie jest kod:** cała praca jest na gałęzi `claude/code-master-prompt-part-2-5651f9` (środowisko sesji pozwalało wypychać tylko tam – patrz `docs/DECISIONS_LOG.md`). **Nic nie jest scalone do `main`.** Do review: PR z tej gałęzi do `main` (squash) – commity są podzielone per kamień milowy.

### Co jest gotowe

| KM | Zakres | Commit | Stan |
|---|---|---|---|
| M0 | monorepo (uv 15 pakietów + pnpm/biome), justfile, pre-commit, ruff/mypy --strict/import-linter, `platform-common` (kontekst tenanta, RLS, audyt z łańcuchem skrótów, OTel, structlog z redakcją, problem+json, kolejki SQS z kontekstem tenanta/śladu, magazyn S3 z prefiksem tenanta), migracja 0001 (role bez BYPASSRLS, tenants, audit), szkielety 4 serwisów z `/healthz` `/readyz`, `deploy/compose` (Postgres+pgvector, moto, LiteLLM + fake LLM, otel-lgtm, Langfuse, Ollama), GitHub Actions (przypięte SHA), Dependabot, szablony | `88211a8`, poprawki po review `158a34c` | ✅ (kryterium `just up && just smoke` potwierdzone w CI) |
| M1 | `bom-core` (model z pochodzeniem per pole, normalizacja wartości/jednostek, obudowy, grupowanie, eksport CSV/JSON, JSON Schema), `cad-parsers` (KiCad 6–9 + CSV BOM, podpowiedzi dla formatów nieobsługiwanych), `rules` core@1.0.0 (w tym flagi IEC 60601), `eval` (P/R/F1, dokładność pól, pokrycie i halucynacje MPN, wstrzykiwanie błędów, powtarzalność), CLI `bomagent parse|bom|eval`, 3 fixture'y KiCad (CC0) | `1d5d335`, poprawki po review `06f838f` | ✅ |
| M2 | `llm` (katalog modeli EU closed/open-weight z bramką weryfikacji, embeddingi gateway/hashing), migracja 0002 (`kb.*` z RLS global/tenant), `kb` (ekstrakcja PDF, chunking, hybryda pgvector+FTS+RRF+reranker, snapshoty, korekty jako wiedza tenanta, flagowanie prompt injection), `kb-indexer` (handler SQS), 18 syntetycznych datasheetów + zestaw zapytań | `4e21c4d` | ✅ |
| M3 | `llm.chat` (gateway z structured output, fałszywy dostawca z kasetami), `agents`: wersjonowane prompty, kontrakt `VariantRuntime`, budżety, `langgraph_b` (hybryda: reguły + agent MPN z RAG tylko dla nierozstrzygniętych + pętla naprawy), `langgraph_a` (100 % LLM), adapter `claude_agent_sdk_a`, MPN tylko z dowodów KB; `fake_server` do compose; CLI `bomagent run --variant A\|B`; `agent-worker` (SQS → wynik w S3 + audyt) | `6c8b783`, `f3ef61d`, poprawki po review w commicie „fix(agents)” | ✅ |
| M4 (część) | migracja 0003 (członkostwa, projekty, pliki, przebiegi, niezmienne wersje BOM, klucze idempotencji – wszystko z RLS; logowanie przez `app.user_sub` bez obejścia RLS), API `/v1` (OIDC JWT + lokalny mock IdP tylko local/test, `X-Org-Id` z członkostwem i rolami z bazy, RBAC, projekty, upload plików → ingest-worker, przebiegi 202 → agent-worker + SSE, BOM JSON/CSV, edycja pozycji → nowa wersja + audyt + korekta w KB, audyt + weryfikacja łańcucha), OpenAPI 3.1 (`services/api/openapi.json`) + testy kontraktowe Schemathesis, klient TS `@bomagent/api-client` z kontrolą dryfu w CI + członkowie i zaproszenia (migracja 0004), złożone FK per tenant (0005), poprawki po security review | `600b6a9`, `c1ca0d9`, `0af9249`, `7f00117`, `377ef94`, `31f63b1` | ✅ (oprócz SSO); gotowe też: klucze API (0006), limity planów, rate limiting i metering (0007), transactional outbox + reaper przebiegów (0008); brak: konfiguracja SSO per organizacja (zależy od Cognito – M6) |
| M5 (część) | `apps/web` (React/Vite/TanStack, tokeny z UX_GUIDELINES): logowanie lokalne, onboarding + dołączanie kodem, przełącznik organizacji, Start z szablonami, projekty + upload, modal Nowy przebieg (A/B/oba), przebieg na żywo (SSE), BOM z paskiem pochodzenia i panelem (uzasadnienie, źródła KB, uwagi, poprawka → nowa wersja), eksport CSV, log audytu, ustawienia (członkowie, zaproszenia, klucze API, zużycie); `packages/ts/ui`; E2E Playwright + axe; `tools/devstack.py` | `f23ec19` + kolejne | 🟡 ok. 60 %; brak: porównanie wariantów, baza wiedzy w UI, oś kroków przebiegu, Cognito/PKCE, zrzuty w PR |
| M6–M8 | CDK, formaty, eksperyment | – | ❌ nie rozpoczęte |

Plany i brainstorming: `docs/plans/M0-foundation.md`, `M1-domain-core.md`, `M2-knowledge-base.md`, `M4-platform-backend.md`.

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
uv run bomagent run evals/fixtures/kicad/ecg-frontend --variant A --reference evals/fixtures/kicad/ecg-frontend/reference_bom.csv
uv run bomagent run evals/fixtures/kicad/ecg-frontend --variant B --reference evals/fixtures/kicad/ecg-frontend/reference_bom.csv
just up && just smoke                # pełny stos dockerowy (niezweryfikowane lokalnie)
# aplikacja webowa lokalnie (bez Dockera): API + workery + nowa baza, potem Vite
BOMAGENT_DEV_ADMIN_URL=postgresql+psycopg://postgres:<hasło>@localhost:5432/postgres uv run python tools/devstack.py
pnpm --filter @bomagent/web dev       # http://127.0.0.1:5173
just e2e                              # Playwright + axe (przy działającym API na :8000)
# samo API lokalnie (mock IdP): token deweloperski z POST /v1/dev/token, potem nagłówki Authorization + X-Org-Id
BOMAGENT_ENVIRONMENT=local BOMAGENT_AUTH_MODE=local BOMAGENT_DATABASE_URL=... uv run python -m bomagent_api   # :8000, /docs
just openapi                         # regeneracja openapi.json + typów klienta TS
```

### Wyniki testów (2026-11-10, lokalnie, Python 3.13, PostgreSQL 16.15 + pgvector 0.6)
- **423 testy Python zielone** + 2 scenariusze E2E Playwright (axe: 0 naruszeń WCAG 2.2 AA) + vitest (web 4, api-client 2); wcześniej: **416 testów zielonych** (unit + integracyjne + izolacji, w tym izolacja projektów/przebiegów/BOM/audytu/zaproszeń i klucze obce między tenantami) + 25 podtestów kontraktowych Schemathesis; pominięte z założenia tylko smoke/e2e.
- Pokrycie: `packages/py/*` **97,4 %** (próg 85 %), serwisy **89,7 %** (próg 75 %).
- Klient TS: typecheck, vitest, biome, brak dryfu względem `openapi.json`.
- ruff, ruff format, mypy --strict (95 plików), import-linter (2 kontrakty) – czyste.
- M3 z fałszywym LLM (hydraulika, nie wynik naukowy): B na eeg-2ch – 4 wywołania LLM, pokrycie MPN 100 %; A – ok. 4× więcej wywołań (ekstrakcja, MPN dla wszystkich pozycji, walidacja, kompozycja).
- Retrieval (M2) na syntetycznym korpusie: recall@5 = 1,00, recall@1 = 0,89 (18 zapytań).
- Smoke natywnie (serwisy uruchomione bez Dockera): `/healthz` + `/readyz` z bazą dla 4 serwisów – zielone.
- Drugi review M4 (klucze, limity, outbox): brak wysokich; 5 średnich naprawionych (`c57cb6d`), niskie odłożone w `DECISIONS_LOG.md`.
- Security review subagentem M4: brak krytycznych; 2 wysokie (FK między tenantami, ponowne dostarczenie `run.requested`) i średnie naprawione; odłożone pozycje w `DECISIONS_LOG.md`.
- Review subagentem po M0, M1 i M3 – wszystkie uwagi wysokiej wagi naprawione (commity `158a34c`, `06f838f` i „fix(agents): address M3 review”).

### Czego nie zrobiono / znane ograniczenia
- **Docker niedostępny w sesji:** stos dockerowy uruchamiany tylko w CI – tam przechodzi (`just up-core` + `just smoke` z trace w Tempo, przebieg Actions #27 dla `2fdcdc9`). Pełne `just up` z Langfuse (profil) nie było jeszcze uruchamiane nigdzie.
- **CI (GitHub Actions):** wszystkie 8 jobów zielone (lint/typy/granice, unit + integracyjne z Testcontainers + progi pokrycia, izolacja tenantów, kontrakt (pusty do M4), TS, compose + smoke, gitleaks + Trivy, cdk (pusty do M6)). Wcześniejsze przebiegi nie startowały (błąd składni workflow) – naprawione w `b9542d9`, `2fdcdc9`.
- Checkpointy LangGraph są w pamięci (nie w Postgresie) – standardowe tabele checkpointów nie mają RLS; decyzja w `DECISIONS_LOG.md`.
- Adapter Claude Agent SDK przetestowany tylko z atrapą pętli `query` (SDK nie instalowany w workspace).
- Ślad w Langfuse niezweryfikowany lokalnie (LiteLLM → OTel → Langfuse działa tylko w stosie dockerowym).
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
5. **Do wystawienia aplikacji pod linkiem (M4–M6):** konto AWS z dostępem do Bedrock w regionie UE, domena (Route 53 lub dostęp do DNS), rola IAM dla GitHub OIDC (przygotuję szablon), weryfikacja domeny w Amazon SES (maile), decyzja: konta lokalne (e-mail + hasło, Cognito) czy od razu SSO. Hostowanie: AWS `eu-central-1` – SPA na S3 + CloudFront + WAF, API/workery na ECS Fargate, Aurora PostgreSQL, logowanie Amazon Cognito. Wdrożenie uruchamiasz Ty z pipeline'u (ja nie tworzę zasobów w chmurze). Pierwszy admin powstanie przy wdrożeniu – hasło ustawiasz z maila, nie przekazujesz mi go.

### Następne kroki (dla kolejnej sesji: „kontynuuj”)
1. M5 – dokończyć: ekran porównania wariantów A/B, baza wiedzy w UI (wymaga endpointów KB w API), oś kroków przebiegu (zdarzenia kroków w SSE), podział paczki JS, zrzuty ekranów w PR.
2. M4 – konfiguracja SSO per organizacja (formularz → Cognito) razem z M6; niskie uwagi z review (DECISIONS_LOG).
3. Checkpointy LangGraph w Postgresie z tabelami tenantowymi (RLS) + test izolacji; budżet i snapshot KB w adapterze Agent SDK.
4. M6: CDK + cdk-nag (`just synth`), szablon roli GitHub OIDC.
5. M7–M8: kolejne formaty, eksperyment `bomagent experiment run` (BioAmp EXG Pill już w `evals/fixtures/kicad-oss/` – potrzebny zweryfikowany ręcznie BOM referencyjny).

## 2026-11-09 – stan wyjściowy
- Gotowe: szablon pracy (DOCX), struktura pracy, diagram wariantów A/B, prototyp przepływu UI (HTML), architektura produkcyjna, 15 ADR, wytyczne UX, roadmapa M0–M8, prompt dla Claude Code.
- Kodu aplikacji jeszcze nie ma – start od M0.
