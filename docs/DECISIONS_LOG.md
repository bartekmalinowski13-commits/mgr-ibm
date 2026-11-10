# Dziennik założeń

Założenia przyjęte bez konsultacji (człowiek niedostępny). Format: data · pytanie · decyzja · uzasadnienie · czy wymaga akceptacji.

| Data | Pytanie | Decyzja | Uzasadnienie | Do akceptacji |
|---|---|---|---|---|
| 2026-11-09 | Co znaczy „Guidance” w liście formatów? | Cadence (OrCAD Capture / Allegro) | brzmienie i kontekst EDA | tak |
| 2026-11-09 | „CDAC” w wymaganiach | AWS CDK | kontekst IaC na AWS | tak |
| 2026-11-09 | Widoczność repo | prywatne | praca przed obroną + potencjalny produkt komercyjny | tak |
| 2026-11-09 | Na którą gałąź pracować, skoro prompt każe scalać do `main`? | Cała praca na gałęzi sesji `claude/code-master-prompt-part-2-5651f9`, commity per kamień milowy; **bez** scalania i pushowania do `main` | środowisko sesji pozwala wypychać tylko na tę gałąź; scalanie do `main` zostawione człowiekowi (squash/PR) | tak |
| 2026-11-09 | Pluginy superpowers / frontend-design niedostępne w sesji | Proces prowadzony ręcznie: brainstorm (tabela w `docs/plans/<KM>`), plan, TDD, review subagentem, weryfikacja | §2 promptu przewiduje ten fallback | nie |
| 2026-11-09 | Docker niedostępny w sesji | Postgres 16 + pgvector 0.6 natywnie (apt) do testów; compose i Testcontainers sprawdza CI | §3 promptu przewiduje ten fallback | nie |
| 2026-11-09 | Emulator S3/SQS i jego licencja | moto (`motoserver/moto`, Apache-2.0) dla S3 i SQS; LocalStack odrzucony – od 03.2026 obraz Community wymaga tokenu konta, MinIO – AGPLv3 i tryb utrzymaniowy | licencja permisywna, jeden kontener na S3+SQS, ta sama biblioteka w testach jednostkowych (`mock_aws`) | tak |
| 2026-11-09 | Gdzie migracje wspólnej bazy? | Pakiet `db-migrations`, ręczne DDL, role migrator/app/platform | ADR-0016 | tak |
| 2026-11-09 | Jak workery wystawiają `/healthz` (smoke test wymaga go dla każdego serwisu)? | Każdy worker to FastAPI z pętlą konsumenta SQS w `lifespan` | jeden wzorzec dla 4 serwisów, health check ECS/ALB | nie |
| 2026-11-09 | Sterownik Postgresa | psycopg 3 (SQLAlchemy async + checkpointy LangGraph) | jeden sterownik w całym stosie | nie |
| 2026-11-09 | Wersja Pythona | `requires-python >=3.12`, CI na 3.12, lokalnie 3.13 | CLAUDE.md: 3.12+ | nie |
| 2026-11-09 | Langfuse lokalnie | Langfuse v4 (web + worker + ClickHouse + Valkey, S3 = moto) w profilu compose `langfuse`; `just up` go włącza, CI (`up-core`) nie | ciężki stos; smoke wymaga tylko Tempo; telemetria Langfuse wyłączona (rezydencja UE) | nie |
| 2026-11-09 | CLI `bomagent` | osobny pakiet `packages/py/cli` (warstwa nad agents) | ARCHITECTURE nie wskazuje miejsca; CLI zależy od wszystkich bibliotek | nie |
| 2026-11-09 | Fixture'y testowe bazy | pakiet `packages/py/testing` (tylko dev), brak bazy = test failuje, nie jest pomijany | testy izolacji blokują merge – nie mogą się „cicho” pominąć | nie |
| 2026-11-09 | Biblioteka PDF dla bazy wiedzy | pypdf (BSD) domyślnie, Docling (MIT) opcjonalnie w obrazie kb-indexer; PyMuPDF odrzucony | FORMATS.md wymienia PyMuPDF, ale jego licencja AGPL-3.0 wymaga licencji komercyjnej w SaaS; Docling ciągnie torch – poza lockiem workspace | tak |
| 2026-11-09 | Wymiar embeddingów i model | `vector(1024)`, model embeddingów z katalogu (Titan V2 / Cohere multilingual na Bedrock EU – do weryfikacji) | stały wymiar wymagany przez HNSW; oba modele mają wariant 1024 | tak |
| 2026-11-09 | Konfiguracja FTS | `to_tsvector('simple', ...)` (bez stemmingu) | dokumenty PL/EN; liczą się tokeny techniczne (MPN, wartości), nie odmiana | nie |
| 2026-11-09 | Modele w katalogu | prawdziwe ID modeli (Bedrock EU, Azure OpenAI Data Zone EU, Mistral, vLLM) z `enabled: false, verified: false`; włącza człowiek po sprawdzeniu dostępności w regionie | ADR-0006; ID modeli i profile EU zmieniają się | tak |
| 2026-11-09 | Korekty użytkowników w KB | zapisywane jako dokument `kind=correction` + wiersz `kb.parts(source=user_correction)` w przestrzeni tenanta | ADR-0008: brak uczenia między organizacjami | nie |
| 2026-11-10 | Sesja Claude Code zatrzymała się po M2 (brak commitów > 3 h). Kto robi M3? | M3 zrealizowany przez Claude z projektu na gałęzi `feat/m3-agents-runtimes` (bazuje na gałęzi sesji) | prośba Bartka: „jak coś blokuje, rozwiążcie”, „rano gotowe do review tyle, ile się da” | tak |
| 2026-11-10 | Checkpointy LangGraph w Postgresie | w M3 parametr `checkpointer` (domyślnie brak); `langgraph-checkpoint-postgres` razem z tabelą przebiegów w M4 | tabele checkpointów muszą dostać RLS i migrację (rola migrator), co jest częścią modułu `runs` w API | tak |
| 2026-11-10 | Fan-out doboru części | `asyncio.Semaphore(RunConfig.concurrency)` w węźle zamiast `Send` LangGraph | deterministyczna kolejność wyników, prostszy ślad; limit współbieżności per przebieg | nie |
| 2026-11-10 | Gdzie reguła „MPN musi być w katalogu KB” | w runtime B (`kb.mpn_known`, pakiet `agents-b@1.0.0`), nie w `rules` | reguły w `rules` są czyste (bez dostępu do KB); wynik i tak trafia do `findings` z wersją pakietu | nie |
| 2026-11-10 | Wariant A: co z odpowiedzią LLM łamiącą schemat BOM (duplikat oznaczenia)? | duplikaty usunięte tylko po to, by zapisać BOM, plus finding `schema.coerced` (error) | wariant A nie może być „po cichu” naprawiany regułami – błąd ma być widoczny w ewaluacji | tak |
| 2026-11-10 | Claude Agent SDK a ADR-0006 (wszystko przez gateway) | adapter `A-sdk` uruchamia się wyłącznie z `CLAUDE_CODE_USE_BEDROCK=1` i `AWS_REGION=eu-*`; oznaczony jako eksperymentalny | SDK woła model bezpośrednio; Bedrock UE zachowuje rezydencję; kod SDK nieprzetestowany na żywym API | tak |
| 2026-11-10 | `fake-llm` w compose | obraz z pakietem `bomagent-agents` (symulatory) i `BOMAGENT_FAKE_LLM_SIMULATOR=bomagent_agents.simulators:simulate`; `agent-worker` z `BOMAGENT_ALLOW_LOCAL_MODELS=true` | stos lokalny działa offline end-to-end; w staging/prod lokalne modele są zablokowane w kodzie | nie |
| 2026-11-10 | M4 w nocy – jaki zakres? | część 1: przebiegi end-to-end przez API (projekty, upload, parsowanie, przebiegi, BOM, SSE, audyt), gałąź `feat/m4-runs-api` | daje działający kręgosłup produktu do review; onboarding/SSO/klucze API/metering w części 2 | tak |
| 2026-11-10 | Tryb uwierzytelniania lokalnie | `BOMAGENT_AUTH_MODE=dev` (HS256, sekret z env, domyślny tylko w compose); w kodzie blokada dla staging/prod | lokalny stos i testy bez IdP; produkcja wyłącznie OIDC | nie |
| 2026-11-10 | Gdzie SQL projektów/przebiegów | `bomagent_common.records` (fundament), używany przez API i workery | serwisy nie mogą importować się nawzajem (import-linter); jedna implementacja statusów | nie |
| 2026-11-10 | Tabela BOM: TanStack Table czy własna? | zwykła tabela HTML + `useMemo` | 22–200 wierszy, brak sortowania wielokolumnowego; mniej zależności; TanStack Table można dodać przy edycji BOM | nie |
| 2026-11-10 | Walidacja formularzy w UI | react-hook-form bez zod (reguły w `register`) | proste formularze; walidacja źródłowa jest w API (Pydantic) | nie |
| 2026-11-10 | Routing | TanStack Router w wersji code-based (bez generatora plików) | 9 ekranów; mniej magii w buildzie | nie |
| 2026-11-10 | Porównanie A vs B w UI | metryki liczone w przeglądarce z BOM + śladów obu przebiegów; „lepszy wynik” tylko dla kosztów (wywołania, tokeny, czas) | jakość (F1, halucynacje) wymaga BOM referencyjnego – to `bomagent eval`, nie UI produktu | tak |
| 2026-11-10 | Tryb mock w UI | `VITE_API_MODE=mock` – dane z prawdziwych przebiegów symulatora, wyraźny znacznik „Tryb demonstracyjny” | review i E2E bez backendu; domyślnie UI używa HTTP | nie |
| 2026-11-10 | Upload do bazy wiedzy | klient liczy SHA-256 i wysyła metadane; API rejestruje dokument (deduplikacja per tenant) i daje presigned PUT; indeksowanie po `complete` | ten sam wzorzec co pliki projektu; hash pozwala odrzucić duplikat zanim plik trafi do S3; serwer i tak liczy hash przy ekstrakcji | nie |
| 2026-11-10 | Edycja BOM przez człowieka a eksperyment | wynik agentów (`bom.json`) niezmienny; poprawki w osobnej kopii `bom.reviewed.json` (migracja 0004), `GET …/bom?version=original` zawsze zwraca oryginał | ewaluacja A/B musi liczyć wynik architektury, nie poprawki ludzi; poprawki i tak są w audycie | tak |
| 2026-11-10 | Walidacja po poprawce | ponownie uruchamiany pakiet `core`; ustalenia innych pakietów (agent, `agents-b`) zostają dla nietkniętych pozycji, a dla poprawionej pozycji są usuwane | dotyczyły decyzji, której już nie ma; pakiet `core` jest deterministyczny i tani | tak |
| 2026-11-10 | „Zapamiętaj” poprawkę | wiadomość `kb.correction.requested` do kb-indexer → `KnowledgeBase.add_correction` w kontekście tenanta | API nie ma klienta embeddingów; nauka tylko w obrębie organizacji (ADR-0008) | nie |
