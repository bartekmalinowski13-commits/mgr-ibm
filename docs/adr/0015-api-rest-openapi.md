# ADR-0015: API: REST + OpenAPI 3.1 + SSE

Status: Accepted · 2026-11-09

## Context
A web client, future customer integrations (public API), streaming of run progress.

## Decision
REST `/v1`, OpenAPI 3.1 generated from FastAPI and committed as the contract; a generated TS client. SSE for run progress. Idempotency-Key for POST, cursor pagination, RFC 9457 errors, request limits per tenant and API key.

## Consequences
A simple, well-supported contract; contract tests (Schemathesis).

## Alternatives considered
GraphQL (per-field authorization complexity); WebSockets (SSE is enough for one-way streaming).
