# ADR-0015: API: REST + OpenAPI 3.1 + SSE

Status: Zaakceptowany · 2026-11-09

## Kontekst
Klient web, przyszłe integracje klientów (API publiczne), streaming postępu przebiegów.

## Decyzja
REST `/v1`, OpenAPI 3.1 generowane z FastAPI i commitowane jako kontrakt; klient TS generowany. SSE dla postępu przebiegu. Idempotency-Key dla POST, paginacja kursorem, błędy RFC 9457, limity zapytań per tenant i klucz API.

## Konsekwencje
Prosty, dobrze wspierany kontrakt; testy kontraktowe (Schemathesis).

## Rozważane alternatywy
GraphQL (złożoność autoryzacji per pole); WebSockets (SSE wystarcza do jednokierunkowego streamingu).
