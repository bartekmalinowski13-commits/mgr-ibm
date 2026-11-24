# web (`@bomagent/web`)

The BOM Agent single-page app (ADR-0014: React, Vite, TanStack Router/Query/Table,
Tailwind, components from `@bomagent/ui`), following `docs/design/UX_GUIDELINES.md`.

- **Responsibility:** the user interface of the SaaS: sign-in (mock IdP locally, Cognito in
  AWS from M6, e-mail + password through Supabase Auth when `/config.json` has
  `auth.mode = "supabase"`), organisation onboarding and switching, projects and uploads, new run
  (variant A / B / both), live run progress (SSE over fetch), BOM table with the
  provenance stripe and item panel (rationale, knowledge-base sources, findings,
  correction as a new version), CSV export, audit log with chain verification, settings
  (members, invitations, API keys, usage and limits, SSO placeholder). PL + EN.
- **Talks to:** only the `/v1` API through the typed `@bomagent/api-client`.
- **Errors and retries:** `problemMessage()` localises problems by slug, else the server detail,
  else a message for the HTTP status (413, 429, 5xx, generic). Creating requests reuse one
  idempotency key per user intent (`lib/idempotency.ts`): a retry of the same form replays, a
  changed form or a submit after success gets a new key. Destructive admin actions confirm first.
- **Design:** "fabrication drawing" (ADR-0019): every screen is a drawing sheet with a title
  block; tokens in `src/styles.css` (vellum/sheet/ink, solder-mask board panel, provenance
  violet = LLM agent, green = rule, grey = design file, ink = person, also coded by glyph
  shape); Archivo (widths 86/100/125) and Martian Mono for technical data. Component preview:
  `/design`. Screens: Start, run (`/runs/:id`, sheet 2), BOM (`/runs/:id/bom`, sheet 3),
  A/B comparison (sheet 4).

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
# ADR-0019 screens against a mocked API (no stack): axe at 1440/375 px + screenshots
pnpm --filter @bomagent/web exec playwright test e2e/visual.spec.ts
# VISUAL_DIR=<dir> writes the screenshots elsewhere; PW_CHROMIUM_PATH=<chrome> uses a
# pre-installed browser of another Playwright build
```
