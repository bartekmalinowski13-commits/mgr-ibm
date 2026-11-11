# Handoff - continue here in a new session

Written 2026-11-11 at the end of the first long build session. A new session should read
this file first, then `CLAUDE.md`, `docs/STATUS.md` (per-milestone state) and
`docs/DECISIONS_LOG.md` (assumptions awaiting the owner's acceptance). This file says
**what is left and in which order**; it does not repeat the specification.

Start prompt for the new session (copy as is):

> Read `docs/HANDOFF.md` and continue with the next open task from its list. Follow
> `CLAUDE.md`. Work on branch `claude/code-master-prompt-part-2-5651f9`.

## Local demo (owner's Mac, no Docker, no LLM keys)

One command starts the API with demo data and the web app; open **http://localhost:5173**.
Everything runs locally: the LLM is the deterministic fake provider, queues and file
storage are in memory, only PostgreSQL is needed. The demo database is created on start
and dropped on exit (Ctrl-C).

One-time setup (Homebrew):

```bash
brew install postgresql@17 pgvector uv node pnpm just
```

```bash
brew services start postgresql@17
```

(Postgres.app with its bundled pgvector works too.) Then, from the repository root:

```bash
just demo
```

(or `./tools/demo.sh` without `just`). If your PostgreSQL admin user is not your macOS
user without a password, set `BOMAGENT_DEV_ADMIN_URL=postgresql+psycopg://user:pass@localhost:5432/postgres` first.

- **URL:** http://localhost:5173 (API on http://127.0.0.1:8000, proxied under `/v1`)
- **Sign in:** e-mail `anna@medtech-demo.example`, any name (local test identity
  provider; any other e-mail starts with an empty account and the onboarding flow)
- **Demo data** (`tools/demo_seed.py`, created through the public API): organisation
  "MedTech Demo" (you are the owner), projects "ECG front-end", "EEG 2-channel",
  "Pulse oximeter" (open KiCad fixtures from `evals/fixtures/kicad`), four finished runs
  (ECG in variant A and B, the others in B). Try: a run's BOM with field provenance, a
  correction, CSV export, comparing A vs B, upload `reference_bom.csv` from the fixture
  folder for the F1 score, the audit log, Settings -> SSO, PL/EN switch at the bottom left.

## Where things are

- **Branch:** `claude/code-master-prompt-part-2-5651f9` (all work; not merged to `main`,
  no PR opened yet - the owner decides). Last commit at handoff: SSO per organisation.
- **CI** (`.github/workflows/pr.yml`, 8 jobs): green up to the parser hardening commit
  (`955328b`). The run for the SSO commit (`2e2253f`) was still running at handoff -
  **check it first** and fix anything red.
- **Milestones:** M0-M5 done; M6 infrastructure code done, **not deployed** (deployment is
  the owner's step, `docs/platform/runbooks/README.md`); M7 formats done (KiCad, CSV,
  IPC-2581, EDIF, ODB++, DXF parts lists, PDF BOM tables); M8 experiment tool done
  (`bomagent experiment run`, statistics, error-injection validation measurement, SVG
  figures + CSV tables for chapter 7) - the real experiment needs the owner's data.
  Also done: live run steps over SSE, SSO per organisation (`docs/plans/M4-sso.md`).
- **Estimated completion of the original task:** about 90 %. The remaining 10 % is
  mostly blocked on the owner (data, model access, AWS) - see the second list.

## Next tasks for Claude Code (in this order)

State after the second session (2026-11-11, evening). Done in this session: CI fix for SSO,
SSO security review + fixes, local demo, LangGraph checkpoints in Postgres (RLS), Agent SDK
budget/snapshot, deferred M4 low items (storage quota, upload races, idempotency scope,
outbox retry limit + cleanup, composite FKs - migration 0011), parsing in a resource-limited
subprocess, `sslmode=verify-full` to RDS, translation of the specification documents.

Still open (in this order):

1. If not yet done at handoff: apply the findings of the review of `6cb5405` (parse sandbox,
   TLS) and `c626bd1` (M4 hardening); finish translating `docs/plans/*`, the runbooks,
   `NEW_SESSION_PROMPT.md`, ADR 0016 and `DECISIONS_LOG.md` (check with
   `git ls-files '*.md' | xargs grep -l -E "ą|ę|ś|ć|ż|ź|ł|ó|ń"`; thesis and supervisor
   report stay Polish).
2. Remaining deferred items (`DECISIONS_LOG.md`): per-IP / per-user limits for paths without
   an organisation (M4 L4), malware-scan enforcement before parsing (GuardDuty tag), LiteLLM
   read-only FS test on the real image, Cognito e-mail via SES, global KB in AWS, EDIF
   hierarchy expansion, SSO MEDIUM-3 (reconcile federated providers after CDK deploys),
   MEDIUM-4 (`auth_time` limit / API key lifetime), LOW-6..9.
3. Resume of crashed runs from LangGraph checkpoints (needs budget/trace restoration; today
   checkpoints are deleted when a run ends and the reaper fails stuck runs).
4. M7 leftovers needing an ADR first: PDF schematics/scans (OCR, vision), native
   Altium/OrCAD/DWG.

## Assumptions awaiting your acceptance

All rows of `docs/DECISIONS_LOG.md` whose last column is "yes"/"tak". Grouped:

- **Process / repository:** "Guidance" = Cadence (OrCAD/Allegro); "CDAC" = AWS CDK; private
  repository; all work on the session branch, no merge to `main` by Claude.
- **Stack choices:** moto instead of LocalStack; one migration package (ADR-0016); pypdf
  instead of PyMuPDF (AGPL); `vector(1024)` embeddings; catalogue models disabled until
  verified in an EU region; Claude Agent SDK adapter as a third runtime; variant A
  extraction input.
- **Research method (thesis):** MPN hallucination guard (MPNs only from KB evidence) in both
  variants; rejected MPNs counted; statistics (paired permutation test, bootstrap, design as
  the unit); validation effectiveness via injected errors; DXF mechanical parts.
- **Platform:** roles from the DB; invitations; API keys; plan limits and storage quotas
  (assumed sizes: pilot 2 GiB, team 20, business 100, enterprise 1000); rate limiting;
  outbox (10 attempts, sent rows kept 7 days) and run reaper; token for the API in AWS; SPA
  session refresh; audit archive; LLM egress outside AWS; supply chain in the pipeline;
  GitHub deploy role trust; WAF in us-east-1 vs the EU-only SCP; HTTPS to origin;
  ingest-worker isolation; parse sandbox default limits (1 GiB, 60 s CPU, 90 s wall);
  RDS CA bundle download unpinned unless `RDS_BUNDLE_SHA256` is given.
- **SSO:** one IdP per organisation in the shared Cognito pool; discovery reveals whether a
  domain uses SSO; deferred review items (MEDIUM-3/4, LOW-6..9).
- **Agents:** LangGraph checkpoints in Postgres, deleted when the run ends.
- **Deferred review items** (M4, M6, M7, SSO) - each listed with its plan.

## Blocked on the owner (Claude Code cannot do these)

1. **Merge:** review the branch, open the PR to `main`, require the
   `tenant isolation (blocking)` check (branch protection).
2. **Experiment data (M8):** at least 6 open biomedical KiCad designs with licences and
   hand-verified reference BOMs (`evals/fixtures/kicad/<design>/reference_bom.csv`),
   datasheets for the global KB (not committed - copyright). With 3 designs the smallest
   attainable p-value is 0.25; 6 gives 0.031.
3. **Model access in the EU:** enable models in Bedrock `eu-central-1` (and optionally
   Azure OpenAI Data Zone EU / Mistral), then set `enabled: true, verified: true` in
   `packages/py/llm/src/bomagent_llm/catalog/models.yaml`; run
   `bomagent experiment run evals/experiments/<real>.yaml` (no real keys in CI).
4. **AWS + domain:** accounts (Organizations, SCPs from `infra/cdk/policies/`), domain and
   certificates (prod requires them), GitHub environments and variables, then
   `AWS_DEPLOY_ENABLED=true` - step by step in `docs/platform/runbooks/README.md`.

## Working environment notes (cloud session)

- PostgreSQL 16 + pgvector runs natively (no Docker): `pg_ctlcluster 16 main start`;
  tests use `BOMAGENT_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres`.
- Commands: `just lint`, `uv run pytest -q`, `pnpm --filter @bomagent/infra exec vitest run`,
  `just synth`, `just openapi` (regenerates the contract and the TS client - run after
  any API change), E2E: start `uv run python tools/devstack.py --port 8000`, then
  `cd apps/web && pnpm exec playwright test --trace off`.
- Local preview for the owner: devstack on :8000 + `pnpm exec vite --host 0.0.0.0 --port 5173`
  in `apps/web`; sign in with any e-mail (mock IdP).
- Fixtures for neutral formats are generated: `PYTHONHASHSEED=0 uv run python tools/make_format_fixtures.py`.
- Never deploy to AWS or create cloud resources from a session (`CLAUDE.md` §6); no real
  LLM keys in tests; never force-push `main`.

## Final report expected at the end

When the list above is done: update `docs/STATUS.md`, summarise for the owner what is
finished, what waits for them (the second list) and which assumptions need their
acceptance, with the percentage of the original task completed.
