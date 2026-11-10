# M4 (część 1) – API przebiegów: projekty, projekty CAD, przebiegi, BOM, audyt

Realizacja: Claude z projektu claude.ai, noc 2026-11-10, gałąź `feat/m4-runs-api` (na `feat/m3-agents-runtimes`).

## Brainstorming – pytania i odpowiedzi
| Pytanie | Decyzja | Uzasadnienie |
|---|---|---|
| Uwierzytelnianie | tylko OIDC (JWT: `sub`, `org_id`, `roles`), weryfikacja podpisu przez JWKS, `iss`, `aud`, `exp`; tryb `dev` (HS256, sekret ≥ 32 znaki) tylko lokalnie/testy – odrzucany w staging/prod | ADR-0005: zależność wyłącznie od OIDC (Cognito w AWS, wymienialny) |
| Autoryzacja | role `owner/admin/engineer/reviewer/viewer`; zapis: owner/admin/engineer; audyt: owner/admin/reviewer | ARCHITECTURE §6 |
| Obiekt innego tenanta | 404 (RLS ukrywa wiersz), nigdy 403 | nie ujawniamy istnienia cudzych danych |
| Upload plików | presigned PUT do `tenants/{t}/designs/{id}/files/{name}`, nazwy plików walidowane wzorcem; `POST /complete` kolejkuje parsowanie | pliki nie przechodzą przez API; parser w sandboxie (ingest-worker) |
| Idempotencja | nagłówek `Idempotency-Key` wymagany przy `POST /v1/runs`; unikalny `(tenant_id, idempotency_key)`; powtórka zwraca 200 i ten sam przebieg | ARCHITECTURE §15 / ADR-0015 |
| Stan przebiegu | `queued → running → completed/failed` aktualizuje agent-worker w transakcji tenanta; powtórzona wiadomość dla zakończonego przebiegu jest potwierdzana bez pracy | dostarczanie at-least-once (SQS) |
| Artefakty | BOM i ślad w S3 (prefiks tenanta), w bazie klucze + usage | duże JSON-y poza Postgresem |
| Postęp na żywo | SSE `GET /v1/runs/{id}/events` (polling bazy co 1 s, zdarzenie przy zmianie statusu) | ADR-0015; wystarczy jednokierunkowy strumień |
| Audyt | każda mutacja: `project.create`, `design.create`, `design.upload_complete`, `design.parse(_failed)`, `run.create`, `run.completed/failed` (aktor `service`); łańcuch skrótów weryfikowany w teście | ADR-0011 |
| Kontrakt | `services/api/openapi.json` (OpenAPI 3.1) commitowany; test porównuje z kodem | ADR-0015 |

## Zrobione
- migracja `0003_projects_runs` (RLS na `app.projects`, `app.designs`, `app.runs`)
- `bomagent_common.records` (SQL wspólny dla API i workerów, paginacja kursorem)
- API: `/v1/projects`, `/v1/projects/{id}/designs`, `/v1/designs/{id}`, `/v1/designs/{id}/complete`, `/v1/runs` (+ `/bom`, `/trace`, `/events`), `/v1/audit/events`
- ingest-worker: `design.uploaded` → parser → `parsed_design.json` + status + audyt
- agent-worker: aktualizacja wiersza przebiegu + audyt
- testy: przepływ end-to-end na prawdziwym Postgresie z RLS, role, izolacja tenantów (marker `isolation`), paginacja, kontrakt OpenAPI, OIDC z kluczami RSA

## Pozostało w M4 (część 2)
Onboarding organizacji (rejestracja, weryfikacja domeny, zaproszenia, członkostwa), konfiguracja SSO per organizacja, klucze API, metering i limity per tenant (tokeny/przebiegi), rate limiting, endpointy bazy wiedzy (upload dokumentów organizacji → kb-indexer), edycja pozycji BOM zapisywana jako wiedza tenanta, checkpointy LangGraph w Postgresie, generowany klient TypeScript z `openapi.json`, Schemathesis na żywym API.
