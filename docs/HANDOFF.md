# Handoff - continue here in a new session

Written 2026-11-11 at the end of the first long build session. A new session should read
this file first, then `CLAUDE.md`, `docs/STATUS.md` (per-milestone state) and
`docs/DECISIONS_LOG.md` (assumptions awaiting the owner's acceptance). This file says
**what is left and in which order**; it does not repeat the specification.

Start prompt for the new session (copy as is):

> Read `docs/HANDOFF.md` and continue with the next open task from its list. Follow
> `CLAUDE.md`. Work on branch `claude/code-master-prompt-part-2-5651f9`.

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

1. **CI check** of the SSO commit; fix red jobs (reproduce locally first).
2. **Security review of SSO** - it was started and stopped at handoff, no findings yet.
   Run a fresh read-only review subagent over: migration
   `packages/py/db-migrations/src/bomagent_migrations/versions/0010_sso.py`,
   `services/api/src/bomagent_api/sso.py`, `services/api/src/bomagent_api/routers/sso.py`,
   the SSO parts of `services/api/src/bomagent_api/auth.py`, the web login/settings
   changes and the API role's `cognito-idp` permissions in `infra/cdk/lib/compute-stack.ts`.
   Focus: cross-tenant membership via another organisation's provider, RLS lookup
   policies (`app.sso_domain` / `app.sso_provider`), enforcement bypass, account
   linking (same e-mail via password and federation), OIDC secret leakage, the Cognito
   `UpdateUserPoolClient` read-modify-write (fields reset, races across API replicas),
   local-only endpoints (`/v1/sso/dev/dns`, dev token `identity_provider`). Fix all
   CRITICAL/HIGH, log the rest in `DECISIONS_LOG.md`.
3. **Deferred review items** (each listed in `docs/DECISIONS_LOG.md` with "Odłożone" /
   "deferred"): M4 low items (storage quota per plan, upload races, idempotency hash
   scope, per-IP limits for paths without an organisation, outbox retry limit and
   cleanup, composite FKs in `kb.*` and `api_keys.replaced_by`); M6 review leftovers
   (malware-scan enforcement before parsing, LiteLLM read-only FS test, Cognito e-mail
   via SES, global KB in AWS, `sslmode=verify-full` with the RDS CA bundle); parser
   leftovers (subprocess CPU/memory limit per parse, EDIF hierarchy expansion).
4. **LangGraph checkpoints in Postgres with RLS** and the KB snapshot/budget in the
   Agent SDK adapter (`docs/STATUS.md`, next steps 4).
5. **Owner's decisions to record:** everything marked "tak/yes" in the last column of
   `docs/DECISIONS_LOG.md` is waiting for acceptance - list them for the owner in the
   final report instead of deciding silently.
6. **Last: translation.** All new documents are English (owner's decision 2026-11-10).
   When everything else is done, translate the remaining Polish documents (`docs/`
   except `docs/thesis/`, `CLAUDE.md`, module READMEs, runbooks, `STATUS.md`,
   `DECISIONS_LOG.md`) to English in one pass; UI stays PL + EN.

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
