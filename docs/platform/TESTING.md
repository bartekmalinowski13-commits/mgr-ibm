# Testing strategy

Principle: **TDD** (the `test-driven-development` skill from superpowers) – test before code. CI is the gate: nothing reaches `main` without a green pipeline.

## Pyramid
| Level | Tools | Scope | When |
|---|---|---|---|
| Static | ruff, mypy --strict, import-linter, biome, tsc, cdk-nag, gitleaks | style, types, module boundaries, secrets, IaC compliance | every commit (pre-commit) and PR |
| Unit | pytest, Hypothesis, vitest, Testing Library | domain logic, value normalization, rules, UI components | PR |
| Integration | pytest + Testcontainers (Postgres+pgvector), S3/SQS emulator, LiteLLM with a fake provider | repositories, RLS, queues, workers, retrieval | PR |
| Tenant isolation | pytest (separate `isolation` marker) | attempts to access other tenants' data via API, SQL, S3, KB, events | PR – **blocks merge** |
| Contract | Schemathesis on OpenAPI; TS client conformance test against the contract | API vs specification | PR |
| E2E | Playwright on the local stack (docker compose) with a fake LLM provider | full user paths in the UI | PR (critical suite), nightly (full) |
| Smoke | pytest + Playwright (tag `@smoke`) | whether the deployment works | after every deployment (dev, staging, prod) and locally `just smoke` |
| LLM evaluations | `packages/py/eval` + `evals/` | BOM quality vs reference (F1, hallucinations, cost) | nightly pipeline with real models (only when secrets are available), locally on demand; regression = alarm |
| Performance | k6 | API p95, queue throughput | nightly on staging |
| Security | CodeQL, Trivy, OWASP ZAP baseline | vulnerabilities | PR / nightly |
| Infrastructure | `aws-cdk-lib/assertions`, snapshots, cdk-nag | CDK stacks | PR |

## Determinism of LLM tests
- In CI the LLM provider = a **fake model** in LiteLLM (responses from recordings in `tests/cassettes/` matched by prompt hash) – tests do not depend on the network or on cost.
- Model quality tests are **evaluations**, not unit tests – they report metrics, not "pass/fail" on a single example (apart from regression thresholds).

## Smoke tests (minimal suite, must pass after every deployment)
1. `GET /healthz` and `/readyz` for each service (including the gateway).
2. Login of the test user of tenant `smoke-a` (locally: local account; in the cloud: a dedicated user).
3. Upload of a sample KiCad project → status `parsed`.
4. Start of a variant B run (fake LLM locally / cheapest model in the cloud) → status `completed`, the BOM has > 0 items.
5. CSV export returns a file.
6. An audit event exists for the run.
7. A user of tenant `smoke-b` gets 404 when trying to read a run of `smoke-a`.
8. The run's trace is visible in the OTel collector (locally: a query to Tempo).

## E2E scenarios (Playwright)
- Organization registration → member invitation → organization switching.
- New run from a template (modal with variant choice) → live progress view → BOM review → item provenance panel → accepting/correcting an item (saved as tenant knowledge) → export.
- Comparison of variants A and B on the same project.
- Admin: SSO configuration (form), roles, limits, audit log with filtering.
- Accessibility: `@axe-core/playwright` on every page (no WCAG 2.2 AA violations).

## Thresholds
Coverage: ≥ 85% for `packages/py/*` (domain core), ≥ 75% for services and the frontend; no drop in coverage in a PR. Zero axe violations. Zero critical/high vulnerabilities without an exception with justification.
