# @bomagent/api-client

Typed TypeScript client for the BOM Agent `/v1` API.

- **Responsibility:** type-safe calls from the web app (M5) to the API. Types are generated from
  the OpenAPI 3.1 contract `services/api/openapi.json` (never edited by hand).
- **Public interface:** `createApiClient({ baseUrl, getToken, getOrgId })` returns an
  `openapi-fetch` client that adds `Authorization: Bearer` and `X-Org-Id`; `unwrap()` turns RFC 9457
  problems into `ApiError`; `idempotencyKey()` creates keys for POST requests.
- **Regenerate:** `just openapi` (exports the spec from FastAPI, then `pnpm --filter @bomagent/api-client run generate`).
- **Test:** `pnpm --filter @bomagent/api-client run typecheck test lint check-generated`.
  CI fails when `schema.gen.ts` drifts from `openapi.json`.
