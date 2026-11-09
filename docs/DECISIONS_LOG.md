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
