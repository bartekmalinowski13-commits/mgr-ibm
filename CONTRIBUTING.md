# Contributing

The rules that always apply are in [`CLAUDE.md`](CLAUDE.md) (tenant isolation, EU only, no
secrets, no deploys from a session, no force-push to `main`). Architecture lives in
`docs/platform/ARCHITECTURE.md` and `docs/adr/`; code that disagrees with them is a bug
unless a new ADR changes the decision.

## Set up

```bash
just doctor      # checks uv, Python 3.12+, Node 22+, pnpm, just, git, docker; prints what is missing
just bootstrap   # uv sync + pnpm install + git hooks
```

Integration tests need PostgreSQL with pgvector: Testcontainers starts it when Docker is
available, or set `BOMAGENT_TEST_DATABASE_URL` (see `packages/py/testing`). No real LLM keys
are ever needed: tests and CI use the deterministic fake provider.

## Daily loop

| Command | What it does |
|---|---|
| `just test-unit` | fast loop, no database |
| `just test` | unit + integration + isolation with coverage |
| `just test-isolation` | cross-tenant isolation suite (blocking in CI) |
| `just lint` | ruff, mypy --strict, import-linter, biome, tsc |
| `just fmt` | format and autofix |
| `just up` / `just down` | local compose stack; `just smoke`, `just e2e` run against it |
| `just demo` | local demo without Docker or LLM keys |

## Making a change

1. Branch from `origin/main`: `feat/<module>-<description>`, `fix/...`, `chore/...`.
2. Write the test first, then the code (TDD). Python 3.12+, `ruff`, `mypy --strict`; TypeScript
   with `biome` and `vitest`.
3. Commits follow Conventional Commits (`feat(cad-parsers): ...`). Code, comments, commits and
   docs are English; thesis documents are Polish; UI strings need PL and EN.
4. Open a PR to `main`; fill in the template (it mirrors the Definition of Done in `CLAUDE.md`:
   module README, OTel spans, audit event for data changes, RLS review for tenant tables).
   Squash merge after green CI.
5. A new architecture decision means a new `docs/adr/NNNN-title.md`. If the spec is unclear,
   pick the option closest to the ADRs and append the assumption to `docs/DECISIONS_LOG.md`.
6. Specification changes go in separate `docs(spec): ...` commits.

## CI

Pull requests run the pipeline in `.github/workflows/pr.yml`. A docs-only change (only
`docs/**` or root `*.md`) skips the Docker, compose-stack and CDK jobs; lint, tests, the
contract check, security scans and `tenant isolation (blocking)` always run.

## Never

Commit secrets or `.env` files, use endpoints outside the EU allowlist, deploy to AWS from a
session, or force-push `main`. Report security issues as described in [`SECURITY.md`](SECURITY.md).
