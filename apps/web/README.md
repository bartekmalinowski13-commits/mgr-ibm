# web (`@bomagent/web`)

The BOM Agent single-page app (ADR-0014: React, Vite, TanStack Router/Query/Table,
Tailwind, components from `@bomagent/ui`), following `docs/design/UX_GUIDELINES.md`.

- **Responsibility:** the user interface of the SaaS: sign-in (mock IdP locally, Cognito in
  AWS from M6), organisation onboarding and switching, projects and uploads, new run
  (variant A / B / both), live run progress (SSE over fetch), BOM table with the
  provenance stripe and item panel (rationale, knowledge-base sources, findings,
  correction as a new version), CSV export, audit log with chain verification, settings
  (members, invitations, API keys, usage and limits, SSO placeholder). PL + EN.
- **Talks to:** only the `/v1` API through the typed `@bomagent/api-client`.
- **Design tokens:** `src/styles.css` (colours of provenance: violet = LLM agent, green =
  rule, grey = design file, ink = person; Bricolage Grotesque for the greeting and page
  titles, IBM Plex Sans/Mono). Plan and design notes: `docs/plans/M5-frontend.md`.

## Run locally
```bash
# API + workers + fresh database on :8000 (needs PostgreSQL 16 + pgvector)
BOMAGENT_DEV_ADMIN_URL=postgresql+psycopg://postgres:...@localhost:5432/postgres \
  uv run python tools/devstack.py
pnpm --filter @bomagent/web dev          # http://127.0.0.1:5173, proxies /v1 to :8000
```
The compose stack (`just up-core`) also serves the API on :8000 and works the same way.

## Test
```bash
pnpm --filter @bomagent/web typecheck test lint
just e2e        # Playwright scenarios from docs/platform/TESTING.md + axe (WCAG 2.2 AA)
```
