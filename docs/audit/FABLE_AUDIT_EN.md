# Fable Audit — mgr-ibm / BOM Agent

**Type:** independent software audit (solution architecture, security, production readiness, research validity)
**Audited revision:** `main` at `1a763f3` (2026-11-16), branch `claude/blissful-sagan-aolsyd`
**Auditor:** Claude (Fable 5.1), acting as IT systems auditor and solution architect
**Polish version:** [`FABLE_AUDIT_PL.md`](FABLE_AUDIT_PL.md)

> Scope assumption requested by the owner: everything that exists in the repository (M0–M8, AWS path, Supabase pilot, experiment tooling) **will be finished as specified**. The audit therefore judges the design and the code as they are, and lists what is still missing for (a) a defensible master's thesis and (b) a production, multi-tenant SaaS for medical-device companies.

---

## 0. Executive summary

The repository is unusually mature for a master's project: a monorepo with 14 Python packages/services and 3 TypeScript packages, forced Row-Level Security on every tenant table, a hash-chained audit log, a transactional outbox, a resource-limited parse sandbox, an EU-only LLM guard, 17 ADRs, a 10-stack CDK deployment, a live pilot on Fly.io + Supabase, and an experiment runner with a sound statistical plan. Static checks (ruff, mypy `--strict`, import-linter, biome, tsc) are clean and the unit suites are green (verified in this session, §9).

The gap between "excellent foundation" and "production SaaS" is nevertheless real. The most important findings:

| # | Finding | Severity | Area |
|---|---|---|---|
| 1 | Variant A is not "100 % LLM": deterministic parser, package/kind heuristics, schema coercion and the evidence-only MPN guard are shared code. The final-BOM hallucination metric is ~0 **by construction**; PB2 must be measured on *attempted* hallucinations. | High (thesis) | TH-01 |
| 2 | The experiment CLI retrieves evidence with **feature-hashing embeddings + lexical rerank** (`InMemoryRetriever`), not the production pgvector + real embedding pipeline. Thesis results would describe a RAG the platform does not run. | High (thesis) | TH-02 |
| 3 | Evaluation dataset: 3 + 5 self-authored small designs; **no real open biomedical design ingested yet**; n ≥ 6 independently verified designs is the minimum for the planned test. | High (thesis) | TH-03 |
| 4 | Live pilot serves **fake-model BOMs without any UI indication**; model catalogue cost figures are placeholders. | High (product/thesis) | UX-01, TH-07 |
| 5 | Access **and refresh tokens live in `sessionStorage`**; SPA CSP allows inline styles → one XSS = full account takeover. | High (security) | SEC-02 |
| 6 | The API process holds the **platform role**, whose `platform_onboarding` policies allow inserting a membership into *any* tenant → a compromised API is a cross-tenant takeover. Needs a narrower contract (SECURITY DEFINER onboarding function or policy constraints). | High (security) | SEC-21 |
| 7 | **No abuse protection before the org context** on the Supabase/Fly pilot (no WAF): `/v1/sso/discover`, `/v1/organizations`, `/v1/invitations/accept`, `/v1/me` are unmetered per IP. | High (security) | SEC-03 |
| 8 | Fly pilot: the parse child shares the container's **network namespace**; API + 3 workers + parser in **one 2 GB machine**; a 64 MiB upload is buffered in RAM. No malware scan anywhere. | High (security/reliability) | SEC-01, SEC-13, SEC-09, ARCH-02 |
| 9 | **No metrics, no alerting, no OTel endpoint on the live pilot**; the SLOs in ARCHITECTURE §11 are unmeasurable. Audit `source_ip` is never set and chain anchors are never exported. | High (operations/compliance) | OPS-01, OPS-02, SEC-04 |
| 10 | **GDPR lifecycle missing**: no tenant export, no deletion (only sample projects), no retention, no sub-processor list in product, no offboarding proof in the audit log. | High (compliance) | SEC-14 |
| 11 | SSO deferred items (removed IdP users keep access ≤ 7 days, non-expiring API keys of SSO members, federation reset on CDK deploy, break-glass without MFA) and **no MFA at all** in the Supabase variant. | Medium/High | SEC-05, SEC-06 |
| 12 | Governance debt: **~60 assumptions in `DECISIONS_LOG.md` await acceptance**, ADR-0017 is "Proposed" while the pilot runs on it, and `ARCHITECTURE.md` describes the target rather than the as-built system. | Medium | DOC-01, DOC-02 |

Scores (details and rationale in §8): thesis 8/10 · production readiness 5/10 · security 7/10 · usability 6/10 · functionality 7/10 · reliability 6/10 · maintainability 8/10 · observability 4/10 · performance & scalability 5/10 · testing 8/10 · documentation 8/10 · research validity 5/10 · compliance & privacy 5/10 · architecture 7/10.

---

## 1. What was audited and how

**Documents:** `CLAUDE.md`, `README.md`, `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/OWNER_CHECKLIST.md`, `docs/ROADMAP.md`, `docs/DECISIONS_LOG.md` (95 rows), `docs/platform/{ARCHITECTURE,SECURITY,TESTING,FORMATS}.md`, ADR-0001…0017, `docs/thesis/*`, runbooks, owner guides, `evals/experiments/*`, `evals/reports/pilot-fake/report.md`.

**Code (read in full or in the security-relevant parts):** `platform-common` (tenancy, db, audit, config, messaging, outbox, storage, logging, health), all 14 migrations and the migrator, `services/api` (auth, authz, app, plans, idempotency, maintenance, all routers), `services/all-in-one`, `agent-worker`, `ingest-worker`, `kb-indexer`, `agents` (runtimes A/B, Claude SDK adapter, retrieval, prompts, checkpoints), `llm` (chat, catalogue, eu_guard, gateway config), `kb` (store, safety), `cad-parsers` (sandbox, registry), `rules`, `eval`, `cli/experiment`, `apps/web` (session, supabase, oidc, api, key screens), `infra/cdk` (skimmed for security posture), `deploy/*`, CI workflows, pre-commit, Dependabot, CodeQL.

**Verification executed in this session** (Python 3.13, Node 22, no Docker daemon, PostgreSQL 16 without pgvector):

| Check | Result |
|---|---|
| `ruff check` + `ruff format --check` | clean (275 files) |
| `mypy --strict` over 16 packages | clean (132 source files) |
| `lint-imports` (2 contracts) | kept |
| `biome check`, `tsc --noEmit` (web, ui, api-client, infra) | clean |
| `pytest -m "not integration …"` | **529 passed**, 177 deselected (DB-backed) |
| `vitest` web / api-client / infra | **49 + 2 + 36 passed** |
| Integration, isolation, contract, E2E, compose smoke | **not run here** (pgvector/Docker unavailable); CI claims green on `main` |

Grep sweeps: no `dangerouslySetInnerHTML`/`eval`/`innerHTML` in the SPA; no secrets, private keys or AWS key patterns in the tree; no `shell=True`, `pickle`, `yaml.load` in Python; no `TODO/FIXME` markers.

**Severity scale:** Critical = exploitable cross-tenant or data-loss issue (none found); High = must be fixed before the first real customer or before the thesis experiment; Medium = before GA / before defence; Low = hygiene.

**Task format:** every finding ends with concrete tasks for an implementing model (Opus/Sonnet). Effort: S ≤ 1 day, M ≤ 1 week, L > 1 week. "AC" = acceptance criteria.

---

## 2. What is already strong (keep it)

- **Tenant isolation is the best part of the system.** Forced RLS on every table (`tenant_table_rls`), no `BYPASSRLS` role, composite `(tenant_id, id)` foreign keys (migration 0005/0011), per-command policies for the platform role, catalogue guard test that enumerates every `tenant_id` table and asserts RLS is forced, a blocking isolation job in CI, tenant-prefixed object keys with path-segment validation, queue envelope tenant check (`queue_messages_envelope_tenant`).
- **Audit log** with DB-side hash chain under an advisory lock, append-only triggers, verification function that refuses to run outside the tenant context.
- **Untrusted-file handling:** parsers never run in the API, `python -I` child with `RLIMIT_AS/CPU`, wall clock, stripped environment, non-dumpable parent, project size bounds, defusedxml, decompression/entity limits, hostile-input fuzz tests.
- **EU-only guard** (`eu_guard.py`) fails the build on a non-EU region/profile/endpoint; Mistral pinned to `api.eu.mistral.ai`; catalogue entries disabled until verified.
- **Prompt-injection boundary:** `<data>` blocks with `<`/`>` escaping, injection-suspect chunks ranked last and excluded from evidence, structured output with schema validation, MPNs only from evidence in every variant, built-in tools denied in the Agent SDK adapter.
- **Operational patterns:** transactional outbox with dead-lettering, run claim (`queued→running`) against at-least-once delivery, stuck-run reaper, idempotency keys bound to user+method+path+body, plan quotas, storage quotas, rate limiting shared across replicas.
- **Engineering hygiene:** `mypy --strict`, import-linter layering, OpenAPI drift check + Schemathesis, coverage thresholds, pinned GitHub Actions, gitleaks + Trivy, Dependabot for 5 ecosystems, cdk-nag with justified suppressions, per-package READMEs, English code/docs, i18n PL/EN from day one, axe in E2E.
- **Research tooling:** versioned prompts with content hash, rule-pack versioning, per-field provenance with citations, experiment manifest, paired permutation test + bootstrap CI with the design as the unit, error-injection validation experiment, SVG/CSV outputs for chapter 7.

---

## 3. Security findings

### SEC-01 · Parse sandbox is a resource boundary, not a network/syscall jail — **High (pilot), Medium (AWS)**
**Evidence:** `packages/py/cad-parsers/src/bomagent_cad/sandbox.py` (docstring says so); ADR-0017 and `DECISIONS_LOG` 2026-11-12 L2. On Fly the child shares the container network and can reach Supabase, the pooler and `mgr-ibm-llm-gateway.internal:4000`.
**Risk:** a parser exploit (ezdxf, pypdf, XML stacks) exfiltrates customer design files or probes internal services.
**Tasks:**
1. (M) Run parsing in a **separate Fly app / process group** with no outbound network (`[[services]]` absent, egress blocked) that consumes the `ingest` queue; the API/web app never imports parsers. AC: `ss -tn` inside the parser shows no connections; integration test proves the parser container cannot resolve DNS.
2. (S) Inside the child: `prctl(PR_SET_NO_NEW_PRIVS)`, `RLIMIT_NOFILE`, `RLIMIT_FSIZE`, and `unshare(CLONE_NEWNET)` where the container allows it (fallback: seccomp profile from the image). AC: sandbox tests assert the limits.
3. (M, AWS) Close the deferred H5 item: ingest task definition without an IAM role for parsing, per-tenant ABAC session policy for S3.

### SEC-02 · Bearer + refresh token in `sessionStorage`, inline-style CSP — **High**
**Evidence:** `apps/web/src/lib/session.tsx` (`write(sessionStorage, SESSION_KEY, next)` incl. `refreshToken`), `services/all-in-one/.../app.py::spa_csp` (`style-src 'self' 'unsafe-inline'`).
**Risk:** any XSS (dependency, markdown in a datasheet title, future rich text) yields a long-lived session (Supabase refresh tokens rotate but are valid for days).
**Tasks:**
1. (M) Introduce a **BFF session**: API exchanges the IdP code for tokens server-side and sets an `HttpOnly; Secure; SameSite=Strict` cookie; SPA calls same-origin with CSRF token (double submit) — or at minimum keep the refresh token server-side and give the SPA 15-minute access tokens only.
2. (S) Tighten CSP: nonce/hash for styles (Tailwind v4 emits a single stylesheet; React `style` attributes can be replaced by classes), add `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, HSTS `preload`.
3. (S) Add an `ErrorBoundary` and Trusted Types (`require-trusted-types-for 'script'`) to the SPA. AC: Lighthouse/Mozilla Observatory ≥ A; E2E asserts CSP headers.

### SEC-03 · No per-IP abuse protection before the organisation context on the pilot — **High**
**Evidence:** `_rate_limit` is applied only inside `org_context`; `DECISIONS_LOG` M4 L4 open ("per IP in the WAF (M6)"); Fly has no WAF; `/v1/sso/discover` is public; `POST /v1/organizations` is bounded only by 3 orgs per user; `/v1/invitations/accept` is unmetered.
**Tasks:**
1. (S) Middleware: token bucket per `Fly-Client-IP` (never `X-Forwarded-For`) for unauthenticated and pre-org routes; stricter buckets for `/v1/sso/discover` and `/v1/invitations/accept`; 429 + `Retry-After`. Store: Postgres `app.rate_windows` (subject = ip) now, Redis later.
2. (S) Make SSO discovery a `POST` with the **domain only** (closes LOW-7), add a constant-time response and a per-IP limit.
3. (S) Fly: lower `hard_limit`, enable Fly's built-in request limits; Supabase Auth: confirm rate limits for sign-up/password reset in the runbook.

### SEC-04 · Audit log lacks source IP and external anchors — **High (compliance)**
**Evidence:** `AuditEvent.source_ip` is never populated (grep `source_ip=` → no call sites); `audit.chain_head()` exists but nothing exports it; ADR-0011 promises S3 Object Lock anchors.
**Tasks:**
1. (S) Capture client IP (CloudFront `CloudFront-Viewer-Address` / `Fly-Client-IP`) and user agent into `TenantContext` and `emit_audit`.
2. (M) Daily job (API maintenance loop or scheduled task) that exports `{tenant, seq, hash, at}` anchors to the Object-Lock bucket (AWS) or to Supabase Storage with a write-once policy + a second copy e-mailed/stored off-platform for the pilot; `GET /v1/audit/verify` uses anchors (`verify_chain(anchors=…)` is already implemented).
3. (S) Add `audit.events` partitioning or archival policy (monthly) before volumes grow.

### SEC-05 · Deferred SSO review items — **Medium → High before an enterprise customer**
**Evidence:** `DECISIONS_LOG` 2026-11-11 "SSO security review - deferred" (MEDIUM-3/4, LOW-6..9).
**Tasks:** (M) reconcile Cognito federation after every deploy (API start + periodic), (S) `auth_time` ≤ 8 h for enforced members, (S) cap API key lifetime (90 days default, 1 year max) and expire keys created by removed/SSO-disabled members, (M) separate broker role with CloudTrail alarm on `UpdateUserPoolClient`, (S) random provider names, (S) require `amr` MFA for owner break-glass and audit each use, (S) periodic TXT re-verification + free-mail domain blocklist.

### SEC-06 · No MFA in the Supabase variant, MFA not enforced for admins on AWS — **Medium**
**Evidence:** ARCHITECTURE §6 "MFA required for admin roles"; no `aal`/`amr` checks in `auth.py`.
**Tasks:** (M) Supabase: enable TOTP MFA, require `aal2` claim for `ADMIN` actions (`authz.require` gains an `mfa=True` flag for member/key/SSO/org management); Cognito: `MfaRequired` for owner/admin groups, same `amr` check. AC: tests for 403 `mfa-required`.

### SEC-07 · Supabase claims: harden the e-mail/verified path — **Low-Medium**
**Evidence:** `oidc_email_verified_claim = user_metadata.email_verified` (user-writable) mitigated by the userinfo check; recommended Custom Access Token hook not yet applied.
**Tasks:** (S) Add the Supabase Custom Access Token hook (server-set `email_verified`), switch the default claim path, keep the userinfo fallback; (S) refuse tokens whose `email` differs from the stored membership e-mail (already done for SSO enforcement — generalise).

### SEC-08 · Pilot secrets handling — **Medium**
**Evidence:** `tools/pilot-llm-setup.sh` writes `LITELLM_MASTER_KEY` to `~/.mgr-ibm-llm-secrets.env`; runbook allows the master key as the app key temporarily; gateway needs a `DATABASE_URL`.
**Tasks:** (S) generate per-app **virtual keys** with budgets and drop the vault file (keep secrets only in `fly secrets` and the owner's password manager); (S) rotate the master key after the stop-gap; (S) document key rotation for DB roles, S3 keys and LiteLLM keys in a runbook.

### SEC-09 · No malware scanning before parsing — **Medium**
**Evidence:** ARCHITECTURE §10 (GuardDuty Malware Protection) deferred (M6 M9); nothing on Supabase.
**Tasks:** (M, AWS) GuardDuty Malware Protection for S3 on the files bucket + worker waits for the `GuardDutyMalwareScanStatus=NO_THREATS_FOUND` tag (bucket policy denies `GetObject` without it); (M, pilot) ClamAV sidecar (`clamd`) in the parser app; files with a positive result are quarantined and audited.

### SEC-10 · Supply chain gaps — **Medium**
**Evidence:** base images by tag (`python:3.12-slim-bookworm`, `node:22-bookworm-slim`, `litellm:v1.108.3`) not by digest; Trivy scans the filesystem, not the built images; no cosign; CodeQL skipped on private repos; no SBOM for the pilot image; no license gate.
**Tasks:** (S) pin digests (Dependabot updates them), (S) Trivy `image` scan job on the three Dockerfiles in `pr.yml`, (S) `pip-licenses`/`license-checker` gate forbidding AGPL/SSPL (the project already took licensing decisions — enforce them), (M) cosign keyless signing + verification in `deploy.sh`, (S) enable GitHub Advanced Security or add Semgrep/Bandit as a PR job.

### SEC-11 · `/docs` and `/openapi.json` exposed in every environment — **Low**
**Evidence:** `create_service_app(..., docs=True)` in the API; the global CSP `default-src 'none'` breaks Swagger UI anyway.
**Tasks:** (S) `docs=settings.environment in {"local","test","dev"}`; publish the contract from the repository instead (Redocly/Scalar page in the docs site).

### SEC-12 · Prompt-injection defence is regex-only and not evaluated — **Medium**
**Evidence:** `bomagent_kb/safety.py` (~8 patterns, PL/EN); no adversarial evaluation set; no canary tokens; LLM free-text fields (`rationale`, finding `message`) rendered in the UI (React escapes, fine).
**Tasks:** (M) adversarial fixture corpus (`evals/fixtures/injection/*`) with an "injection success rate" metric in `bomagent experiment`; (S) canary string in the system prompt whose presence in output marks a compromised call; (S) size-cap and unicode-normalise LLM free text before storage; (M) optional LLM-classifier for suspect chunks (fast model, tenant-scoped, EU).

### SEC-13 · Memory-bound uploads and parsing on a shared 2 GB machine — **High (pilot)**
**Evidence:** `upload_file` reads 64 MiB into memory while holding the tenant row lock; `ProjectSize` allows 256 MiB per project loaded by the worker; parser child `RLIMIT_AS` 1 GiB; Fly VM 2 GB shared with the API.
**Tasks:** (M) presigned PUT uploads (the `ObjectStore` protocol already has `presign_put`) + a `POST …/files/complete` call that records sha256/size from the object head; (S) stream multipart to a temp file (`SpooledTemporaryFile`) when direct upload is kept; (S) bound concurrent parses per worker (semaphore = 1) and per tenant (plan); (S) alert on OOM kills.

### SEC-14 · GDPR / data lifecycle not implemented — **High (compliance)**
**Evidence:** no export endpoint, `DELETE /v1/projects/{id}` only for samples, no file/run/KB-document deletion, no retention sweeper, no offboarding workflow; SECURITY.md promises all of these.
**Tasks:** (L) `POST /v1/organizations/{id}/export` (async job → ZIP of projects, BOM versions, KB docs, audit log) and `DELETE /v1/organizations/{id}` (owner + MFA + confirmation; soft-delete 30 days then hard delete incl. objects, checkpoints, queue rows; final audit event + anchor); (M) project/file/run/KB-document deletion with `file-in-use` checks; (M) per-tenant retention settings and a maintenance sweep; (S) `docs/legal/SUBPROCESSORS.md` + in-app link; (S) DPA template checklist for Supabase/Fly/AWS/LLM providers.

### SEC-15 · Platform-role blast radius in the API process — **High (defence in depth)**
**Evidence:** migrations 0001/0003: `platform_onboarding` policies `USING (true) WITH CHECK (true)` on `tenancy.tenants` and `tenancy.memberships` for `bomagent_platform`; the API holds `platform_engine` for onboarding, maintenance and (all-in-one) queue consumption.
**Risk:** an RCE/SSRF in the API lets an attacker insert an `owner` membership into any tenant.
**Tasks:** (M) replace direct inserts with a `SECURITY DEFINER` function `tenancy.create_organization(slug, name, owner_sub, email, display_name)` owned by the migrator, executable by `bomagent_platform`, that creates tenant + first owner atomically and nothing else; revoke `INSERT` on `tenancy.memberships` from the platform role; (S) policy on the platform `memberships` insert limited to tenants with zero members; (M, AWS) give the maintenance/outbox relay its own minimal role (read tenant ids only) and keep the onboarding role out of the API containers that serve traffic (separate `onboarding` task or Lambda-like endpoint).

### SEC-16 · Session-start hook and plugin auto-enable — **Low (process)**
**Evidence:** `.claude/settings.json` runs `git merge --ff-only origin/main` on every session start and enables two plugins. Harmless (`--ff-only`) but surprising on feature branches; document it in `CLAUDE.md`.

### SEC-17 · Additional low items
- `FORWARDED_ALLOW_IPS=*` on Fly — never derive security decisions from `X-Forwarded-For` (use `Fly-Client-IP`); add a comment-level guard in `auth.py`.
- Error texts from parsers (`str(exc)[:500]`) are stored in `files.summary` and shown in the UI: ensure no file paths or library internals leak (add a test with a crafted DXF).
- Add a root `SECURITY.md` with a vulnerability disclosure policy and a `CODEOWNERS`; enable branch protection with the `tenant isolation (blocking)` check (owner task, listed in HANDOFF).
- Idempotency responses are stored for ever (`app.idempotency_keys` has no sweep) — add a 24 h TTL to the maintenance loop.

---

## 4. Architecture findings

### ARCH-01 · Two deployment variants, the weaker one is live — **High (strategic)**
AWS multi-service (thesis narrative, never deployed) vs Supabase/Fly all-in-one (live pilot, ADR-0017 "Proposed", weaker guardrails). Every change must be tested twice; the pilot is where real users will form their opinion.
**Recommendation:** decide explicitly. Option A (recommended for the next 6 months): make the Fly/Supabase path a first-class "Standard tier" with the hardening in SEC-01/03/13 and ARCH-02, keep AWS as the "Enterprise/silo tier" roadmap. Option B: deploy AWS dev now and retire the pilot after the defence. Either way: one composition root (`bomagent_allinone` already composes the services) with profiles, and a CI matrix that runs the same E2E suite against both.
**Tasks:** (S) ADR-0018 "Deployment tiers"; (S) accept/reject ADR-0017; (M) E2E job against the all-in-one image in CI.

### ARCH-02 · Single process = no isolation, no horizontal scaling — **High (pilot)**
**Tasks:** (M) Fly process groups: `web` (API+SPA, 2 machines, rolling deploy), `worker` (ingest/agent/kb consumers, 1–2 machines, no public port), `parser` (SEC-01), `gateway`; `release_command` stays; `/readyz` per group. AC: deploying the API does not interrupt a running agent run; a parse OOM does not restart the API.

### ARCH-03 · O(tenants) maintenance, per-request DB writes, SSE polling — **Medium**
**Evidence:** `maintenance.sweep` opens 3 transactions per tenant every 30 s; `hit_rate_limit` writes a row per request; `run_events` polls per client per second; the Postgres queue polls every 1 s.
**Tasks:** (S) outbox relay: one platform-role query over pending rows ordered by `created_at` with `tenant_id` returned, then tenant-scoped delivery; (S) `LISTEN/NOTIFY` on `runs.runs` updates and on `app.queue_messages` inserts to replace polling; (M) when > 50 tenants or > 100 rps: Redis/ElastiCache (or Fly Upstash) token bucket; (S) index `runs.runs (tenant_id, project_id, status)` for `refuse_if_run_active`.

### ARCH-04 · Raw SQL in routers; no service layer — **Medium**
**Evidence:** 25 `noqa: S608` f-string SQL sites; `routers/runs.py` imports helpers from `routers/projects.py`; business rules live in routers (quota checks, audit, outbox).
**Tasks:** (M) introduce `bomagent_api/services/{projects,runs,members,kb}.py` (transaction + audit + outbox orchestration) and `bomagent_api/repositories/*.py` (SQLAlchemy Core `Table` objects for compile-time column safety; RLS unchanged); routers become thin. AC: no SQL text in routers; import-linter contract `routers -> services -> repositories`.

### ARCH-05 · No resume from checkpoints; checkpoints deleted at run end — **Medium**
**Evidence:** `agent-worker/handler.py` deletes the thread in `finally`; reaper fails runs after `run_timeout_s`. Long designs (HealthyPi-class, > 300 lines, fan-out 8) risk timeouts.
**Tasks:** (M) resume path: on redelivery of `run.requested` for a `running` run whose worker died (heartbeat column), restore `Budget` from `runs.usage` and `ctx.trace`, `ainvoke(None, config)` from the last checkpoint; (S) `started_at`/`heartbeat_at` instead of a fixed 1 h timeout; (S) per-plan `run_timeout_s`.

### ARCH-06 · KB snapshot never created for API runs — **Medium (reproducibility)**
**Evidence:** `POST /v1/runs` does not call `KnowledgeBase.snapshot`; `kb_snapshot_id` arrives as `None` from the payload; R10 and ADR-0008 require a snapshot per run.
**Tasks:** (S) create (or reuse the latest unchanged) tenant snapshot at run creation, store the id on the row, pass it to the worker; show it in the run page and in CSV export metadata.

### ARCH-07 · Embeddings silently fall back to hashing — **Medium**
**Evidence:** `HashingEmbeddings()` when no gateway in API and all-in-one; `/readyz` reports only `llm`.
**Tasks:** (S) `readyz_info.embeddings = fake|gateway`; refuse hashing outside local/test unless `BOMAGENT_ALLOW_FAKE_LLM`; UI banner (UX-01).

### ARCH-08 · Gateway config baked at build time — **Low**
Enabling a model = rebuild + redeploy of the gateway. Acceptable now; later: signed runtime config in object storage with the same `eu_guard` check at gateway start (`check_environment` exists but is not wired — wire it).

### ARCH-09 · Target vs as-built drift — **Medium**
EventBridge → audit archive, Langfuse, ADOT/Prometheus/Grafana, GuardDuty gating, SES e-mail, per-tenant LLM budgets in the gateway, silo deployment: present in diagrams, absent in code. **Task:** (S) add an "As built (2026-11)" section to `ARCHITECTURE.md` with a table "component → status (implemented / configured / planned) → evidence path".

### ARCH-10 · Repository hygiene — **Low**
`evals/samples` is a symlink into `services/api` (breaks on Windows checkouts without developer mode and surprises Docker contexts): replace with a build step or a package-data copy. Module versions are all `0.1.0` with no tags/CHANGELOG: adopt release tags + `CHANGELOG.md` (keep-a-changelog) before the first customer.

---

## 5. Reliability, operations, data

### OPS-01 · No observability on the live pilot — **High**
**Evidence:** `fly.toml` sets no `BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT`; Langfuse only in compose; no alerting.
**Tasks:** (S) Grafana Cloud (EU region) or self-hosted LGTM in Fly: OTLP endpoint + auth header; (S) alert rules: 5xx rate, `/readyz` failures, queue age > 10 min, dead letters > 0, outbox dead rows > 0, run failure rate, Fly OOM events; (S) uptime check from outside (EU probe); (S) error tracking (Sentry EU or GlitchTip) with PII scrubbing.

### OPS-02 · No metrics at all (traces only) — **High**
**Tasks:** (M) OTel metrics in `platform-common.telemetry`: HTTP RED metrics (auto-instrumentation gives them), `bomagent_runs_total{status,variant}`, `bomagent_run_duration_s`, `bomagent_llm_tokens_total{tenant,model}`, `bomagent_llm_cost_eur_total`, queue depth/age per queue, outbox pending/dead, parse durations and failures by code. AC: dashboards JSON committed under `deploy/observability/`.

### OPS-03 · DLQ / dead outbox have no tooling — **Medium**
**Tasks:** (S) `bomagent-ops` CLI: `outbox list|requeue|dead`, `queue dead list|requeue|purge`; (S) metrics + alarms (OPS-02); (S) runbook "message stuck".

### OPS-04 · Deploy = downtime, no rollback plan — **Medium**
**Tasks:** (S) expand/contract migration policy documented in `db-migrations/README.md` and enforced in review (no column drops in the same release); (S) Fly rolling strategy with 2 `web` machines after ARCH-02; (S) `fly releases rollback` runbook; (S) smoke test after deploy in CI (`tests/smoke` against the pilot with a dedicated smoke tenant — the suite exists but targets compose only).

### OPS-05 · Backups and DR — **Medium**
**Tasks:** (S) Supabase paid plan with PITR for the pilot (free plan pauses projects); (M) nightly restore drill job (AWS: restore snapshot to a scratch cluster, run `verify_chain` and row counts; Supabase: `pg_dump` to EU object storage + restore test); (S) RPO/RTO stated in a runbook.

### OPS-06 · Runbooks missing — **Medium**
Incident response, security incident + breach notification (72 h GDPR), key rotation, restore, tenant offboarding, on-call/escalation, capacity. `SECURITY.md` references `docs/runbooks/` which does not exist (actual folder: `docs/platform/runbooks/`). **Task:** (M) write them; fix the path.

### OPS-07 · CI cost and speed — **Low**
Every push to `claude/**` runs 9 jobs incl. 3 Docker builds. **Tasks:** (S) path filters, GHA cache for uv/pnpm/Docker layers, `concurrency` already set; (S) nightly job for the heavy matrix.

### OPS-08 · Migration safety — **Medium**
Hand-written SQL lists, no downgrade tests, no lock-time linting. **Tasks:** (S) `squawk` or `pg-safe-migrations` in CI; (S) test that applies all migrations, downgrades one step and upgrades again; (S) `.python-version = 3.12` to match CI.

### OPS-09 · Capacity and performance unknown — **Medium**
No k6 tests (TESTING.md lists them), no measured p95, LangGraph `concurrency=8` default with no per-tenant cap at the gateway. **Tasks:** (M) k6 scenarios (upload, run, SSE, BOM read) against the compose stack nightly; (S) per-tenant LiteLLM virtual keys or `metadata.tenant_id` budgets and parallelism limits; (S) publish a capacity note (runs/hour per machine size).

### DATA-01 · Growth and indexes — **Low-Medium**
`runs.runs.trace` and `bom.versions.content` are whole-document JSONB; `idempotency_keys` and `rate_windows` grow; only `runs_tenant` index. **Tasks:** (S) indexes `(tenant_id, project_id, status)` on runs and `(tenant_id, project_id)` on files; (S) TTL sweeps; (S) size caps on `trace` (keep last N steps or move to object storage).

### DATA-02 · Embedding model migration path — **Low**
`vector(1024) NOT NULL` fixed dimension. **Task:** (S) document the re-index procedure; consider `halfvec` and a per-model chunk table when a second model is enabled.

---

## 6. Quality, testing, UX, documentation

### QA-01 · Verified state
Strong pyramid (see §2). Gaps below.

### QA-02 · No recorded real-model cassettes — **Medium**
`tests/cassettes` does not exist; `FakeChat` replays nothing; "recorded responses" in TESTING.md are aspirational. **Tasks:** (S) `bomagent record` command that stores real responses + usage under `tests/cassettes/<model>/`; (M) nightly eval job with a real EU model behind GitHub environment secrets (never in PR CI) that fails on regression thresholds (line F1, attempted hallucination rate).

### QA-03 · Property-based and mutation testing — **Low**
Hypothesis used in 2 files only; value normalisation, refdes grouping and CSV parsing are ideal targets. **Tasks:** (S) Hypothesis strategies for `values.py`, `grouping.py`, `csv_bom.py`; (S) `mutmut` on `bom-core` and `rules` once per release.

### QA-04 · E2E breadth — **Medium**
5 specs on the mock IdP; Supabase sign-in/social flows only unit-tested; no mobile viewport, no visual regression. **Tasks:** (M) Playwright against the all-in-one image with a Supabase-compatible stub (GoTrue in Docker) or a contract-level stub; (S) mobile project in `playwright.config.ts`; (S) screenshot comparison for BOM table, run page, settings.

### QA-05 · DAST and license gates missing — **Medium**
**Tasks:** (S) OWASP ZAP baseline job against the compose stack (nightly); (S) license gates (SEC-10).

### UX-01 · Demo mode is invisible — **High**
Pilot answers with the fake model; no banner; BOMs look real; `readyz` shows `"llm":"fake"` but users do not read it. **Tasks:** (S) `/config.json` gains `{"mode":"demo","llm":"fake","embeddings":"fake"}`; persistent top banner PL/EN "Demo mode — deterministic model, BOMs are illustrative"; watermark in CSV export header and in `bom.json` (`"demo": true`); block "Compare with reference" claims in demo mode or label them.

### UX-02 · Invitations without e-mail — **Medium**
Inviter must copy a token manually. **Tasks:** (M) transactional e-mail (SES eu-central-1 for AWS; Supabase SMTP/Resend EU for the pilot) with an `/invite/<token>` landing page; (S) resend + expiry display.

### UX-03 · Missing lifecycle actions — **Medium**
No project rename/delete (non-sample), no file delete, no run cancel, no BOM version history/diff view, no XLSX export, no run re-execution with the same snapshot. **Tasks:** (M) implement with audit events and `file-in-use` checks; (S) version history list + diff of two versions (the data model already supports it via `parent_id`).

### UX-04 · BOM table at scale — **Medium**
Core row model only: no sort, filter, column resize, virtualisation. A 400-line BOM with findings filter is already heavy on mobile. **Tasks:** (M) TanStack sorting/filtering + `@tanstack/react-virtual`; (S) sticky header, column visibility, CSV copy.

### UX-05 · Error messages not localised — **Medium**
`problemMessage()` shows the English `detail`. **Task:** (S) map `slug` → i18n key with the detail as fallback; cover all slugs in `locales/*.json` (a test enumerates slugs from `openapi.json`).

### UX-06 · Focus management — **Low-Medium**
`ItemPanel` closes on Esc but has no focus trap and does not return focus to the row; dialogs from Radix are fine. **Task:** (S) use the `@bomagent/ui` Dialog/Sheet primitive for the drawer breakpoints; return focus on close; announce version saved via `aria-live`.

### UX-07 · Quota awareness and empty states — **Low**
Usage is admin-only; no warning at 80 % of runs/storage; no first-run checklist beyond samples. **Tasks:** (S) quota chips in the shell for all roles (read-only), toasts at thresholds; (S) "first BOM in 3 steps" checklist card on Start.

### UX-08 · Accessibility regression gate — **Low**
axe runs in E2E (good). Add `prefers-reduced-motion` and colour-contrast checks for provenance colours in both themes; add `lang` switch to `<html>` on load before first paint (currently set in `i18n.ts` after init — fine, keep).

### DOC-01 · Target vs as-built, overlapping status files — **Medium**
`STATUS.md`, `HANDOFF.md`, `OWNER_CHECKLIST.md` overlap and drift (HANDOFF still says nothing is merged to `main`). **Tasks:** (S) `STATUS.md` = as-built + known gaps (single source), `HANDOFF.md` archived under `docs/history/`, `OWNER_CHECKLIST.md` kept as the owner's to-do; (S) fix `README.md` "15 ADRs" → 17; (S) add an "As built" section to `ARCHITECTURE.md` (ARCH-09).

### DOC-02 · Decision governance debt — **Medium**
~60 `DECISIONS_LOG` rows await acceptance; several are architecture-level (Supabase variant, queue backend, token in SPA, API key model, plan limits). **Tasks:** (S, owner) accept/reject in one pass; (S) promote accepted architectural ones to ADRs (ADR-0018 deployment tiers, ADR-0019 Postgres queue, ADR-0020 session model); (S) a CI check that `DECISIONS_LOG` rows older than 60 days with "yes" fail a nightly job (visibility, not blocking).

### DOC-03 · Licensing and legal — **Medium**
No root `LICENSE`; fixtures CC0 with SOURCE files (good); thesis needs a statement; product needs ToS/Privacy/DPA drafts. **Tasks:** (S) `LICENSE` (proprietary "All rights reserved" or a chosen OSS licence — owner decision) + `NOTICE` for third-party fixtures; (M) legal document drafts under `docs/legal/` to be reviewed by a human lawyer.

### DOC-04 · Developer experience — **Low**
`just` targets fine; add `just doctor` (checks Postgres+pgvector, Node, uv), a `docs/CONTRIBUTING.md`, PR template already exists; publish OpenAPI as a static page.

---

## 7. Thesis and research validity

### TH-01 · Construct validity of "variant A = 100 % LLM" — **High**
**Evidence:** `variant_a.py` uses the deterministic parser output (documented), `kind_of`, `package_from_footprint`, Pydantic coercion (`lines_to_items` drops malformed lines), `guard_mpns` (deterministic evidence filter) in *both* variants; `finish()` applies `guard_mpns` again. `metrics.py` computes `mpn_out_of_reference`/`unverified` on the **final BOM**, which the guard has already cleaned.
**Consequence:** PB2 ("hallucination rate") on the final BOM is ~0 for both variants by construction (the pilot report shows 0.000 everywhere); the measurable phenomenon is the *attempted* hallucination recorded as `agent.mpn_rejected` findings.
**Tasks:**
1. (S) Define in `docs/thesis/METODYKA.md` the exact division of labour: which deterministic code both variants share (parser, schema coercion, MPN guard, metrics) and why (safety floor identical for A and B). State explicitly that A is "LLM-maximal within a guarded contract".
2. (S) Add metric `attempted_mpn_hallucination_rate = rejected MPN decisions / all MPN decisions` (from findings) as the **primary PB2 metric**; keep the final-BOM rate as a secondary "residual" metric; add both to `experiment` tables and figures.
3. (M) Optional ablation `A-unguarded` (guard disabled, flag in `RunConfig`) run on the same matrix to quantify what the guard removes — valuable for chapter 7 and for the product argument.
4. (S) Report rule-pack coverage of injected error kinds (TH-10).

### TH-02 · Experiment RAG differs from production RAG — **High**
**Evidence:** `cli/experiment.py` builds `InMemoryRetriever.from_directory(config.kb_dir)` → `HashingEmbeddings` (feature hashing, non-semantic) + `LexicalReranker`. Production uses pgvector + gateway embeddings + FTS + RRF.
**Tasks:** (M) `experiment run --retriever postgres --embedding-model <catalogue id>` that indexes `kb_dir` into a scratch tenant via `KnowledgeBase` and snapshots it (`kb_snapshot_id` in the manifest); (S) record retriever type, embedding model and snapshot id in `manifest.json`; (S) if hashing is kept for cost reasons, say so in chapter 6 as a limitation and run at least one configuration with real embeddings to show the sensitivity.

### TH-03 · Dataset size and independence — **High**
**Evidence:** 3 KiCad fixtures + 5 sample designs, all self-authored and small; `ZBIOR_EWALUACYJNY_KANDYDACI.md` lists real candidates but none is ingested; reference BOMs are generator-derived.
**Tasks:** (L, owner + model) ingest ≥ 6 real open designs (BioAmp EXG Pill, Ganglion, HealthyPi Move, Card/IO, dcmini, S1 ECG; licences + `SOURCE.md`), build reference BOMs with **two independent verifiers** and report inter-rater agreement; stratify by size (small/medium/large); keep self-authored designs as a separate "control" set (they allow controlled error injection) and never pool them with real designs in the headline statistics.

### TH-04 · Statistical plan refinements — **Medium**
Paired permutation on per-design means (n = 6–8) is honest but weak; 15 metrics × 2 models invites multiplicity. **Tasks:** (S) pre-registration note (`docs/thesis/PREREJESTRACJA.md`): primary metrics (line F1, attempted hallucination rate, cost per BOM), secondary metrics, Holm correction for the primary family; (S) add per-line GEE/mixed-effects or a cluster bootstrap as a sensitivity analysis; (S) report standardised effect sizes next to raw differences.

### TH-05 · Models and costs — **High before the experiment**
Catalogue costs are placeholders; no model is enabled; closed vs open-weight dimension needs ≥ 1 model per class in the EU (Bedrock Claude, Mistral Large; Qwen3/gpt-oss on Bedrock EU). **Tasks:** (S) update prices from provider price lists with a date and source URL per entry; (S) enable/verify entries after owner access; (S) record exact model ids/versions in the manifest; (S) decide on temperature (0) and seeds, and document non-determinism of hosted models.

### TH-06 · Validation-effectiveness experiment circularity — **Medium**
Injected error kinds (`drop_footprint`, `drop_mpn`, `duplicate_refdes`, `footprint_size_swap`, …) are exactly what `core@1.0.0` checks → B reaches 1.000 on the fake pilot. **Tasks:** (S) add error classes outside rule coverage (wrong-but-plausible MPN, obsolete part, voltage derating, wrong tolerance, package mismatch not detectable from the string); (S) report rule coverage per class; (S) report false alarms per class.

### TH-07 · Claude Agent SDK runtime — **Medium**
Tested only with a scripted `query`; either run it for real on Bedrock EU (and include as a third arm, "off-the-shelf agent") or drop it from the thesis scope and keep it as future work.

### TH-08 · Chapter mapping and appendices — **Low**
Generate Appendix A (prompts with versions/hashes), Appendix B (JSON Schema), Appendix C (run instructions) from the repository at build time (`tools/build_docx.js` could embed them); add a table "research question → metric → code path → test".

### TH-09 · Supervisor-facing report — **Low**
`docs/supervisor/raport-postepu.pdf` exists; keep a one-page "experiment status" updated from the manifest.

---

## 8. Scores (1–10) with rationale

| Category | Score | Why |
|---|---|---|
| **Overall as a master's thesis** | **8** | Engineering depth, reproducibility tooling (versioned prompts, manifests, statistics) and documentation far exceed the typical thesis. Held back by: no real-model results yet, dataset not collected, construct-validity issue TH-01 and the RAG mismatch TH-02. With TH-01…05 addressed it is a 9. |
| **Production readiness (SaaS)** | **5** | Foundation (tenancy, audit, quotas, outbox, IaC) is production-grade; but nothing is deployed on the primary path, the pilot runs a fake model in a single machine with no observability, no MFA, no GDPR lifecycle, no e-mail, no abuse protection, and ~60 unaccepted decisions. |
| **Security** | **7** | Tenant isolation, audit chain, sandbox, EU guard and review discipline are excellent. Deductions: token storage model, platform-role blast radius, missing MFA/rate limits/malware scan/anchors, deferred SSO items. |
| **Usability** | **6** | Clean flow (upload → run → BOM with provenance → correction → export → compare), i18n and accessibility in place. Deductions: invisible demo mode, manual invitations, English-only errors, no table sorting/virtualisation, missing lifecycle actions. |
| **Functionality** | **7** | Both variants, 7 formats, KB with corrections, SSO, API keys, plans, A/B comparison, reference evaluation, experiment runner. Missing: deletion/export, run cancel/resume, e-mail, real models, PDF schematics/Altium/DWG (documented limitation). |
| **Reliability & resilience** | **6** | At-least-once with claims, outbox, reaper, quotas. Deductions: single process pilot, no resume, deploy downtime, no DR drill, no alerting. |
| **Maintainability & code quality** | **8** | Strict typing, layering enforced, clear docstrings, small functions, consistent conventions. Deductions: raw SQL in routers, a few 500–700-line modules, no service layer. |
| **Observability** | **4** | Traces, structured logs with redaction and health endpoints exist in code; nothing is wired on the live pilot; no metrics, no alerts, no Langfuse in any deployed path. |
| **Performance & scalability** | **5** | Fan-out, structured output, tiering hooks exist; no measurements, polling-based SSE/queue, O(tenants) sweeps, DB-write rate limiting, memory-bound uploads. Fine for a pilot, unproven beyond. |
| **Testing & QA** | **8** | 706 Python tests incl. a blocking isolation suite, contract tests, fuzzing, CDK tests, E2E + axe; coverage gates. Deductions: no real-model cassettes/evals, small E2E breadth, no DAST/perf. |
| **Documentation** | **8** | Exceptional volume and quality (ADRs, runbooks, owner guides, decision log, READMEs). Deductions: drift between status files, target-vs-as-built gap, unaccepted decisions. |
| **Research validity (experiment)** | **5** | Tooling 9/10; evidence 2/10 today: fake-provider results only, hashing RAG, self-authored designs, placeholder costs, guard-induced zero hallucination metric. |
| **Compliance & privacy (GDPR, EU, medtech)** | **5** | EU-only enforcement and audit/provenance are strong; missing export/deletion/retention, sub-processor list, DPA posture, IP in audit, anchors, MFA. |
| **Architecture** | **7** | Target architecture is sound and well argued (modular monolith + 3 workers, pooled RLS with silo option, gateway). As built: dual deployment paths, single-process pilot, several promised components absent. |

---

## 9. Recommended order of work

**Phase 0 — before any real user data on the pilot (≈ 2 weeks)**
UX-01 demo banner · SEC-03 per-IP limits · SEC-13 presigned uploads + parse semaphore · ARCH-02 process groups (+ SEC-01 parser isolation) · OPS-01/02 OTel endpoint, metrics, alerts · SEC-04 source IP + anchor export · DOC-02 accept decisions, ADR-0017/0018 · SEC-08 virtual keys.

**Phase 1 — thesis experiment (≈ 4–6 weeks, parallel to phase 0)**
TH-05 models + prices · TH-02 Postgres retriever in the experiment · TH-01 attempted-hallucination metric + method note · TH-03 dataset ingestion with double verification · TH-06 extra error classes · TH-04 pre-registration · run the matrix · chapter 7 figures.

**Phase 2 — first paying pilot customer (≈ 6–8 weeks)**
SEC-02 BFF session + CSP · SEC-15 onboarding function · SEC-06 MFA · SEC-14 export/delete/retention · UX-02 e-mail invitations · UX-03 lifecycle actions · SEC-09 malware scan · OPS-04/05/06 deploy, backup, runbooks · SEC-10 supply chain · QA-02 nightly real-model evals · ARCH-06 KB snapshots per run.

**Phase 3 — scale and enterprise (quarter 2)**
ARCH-03 LISTEN/NOTIFY + Redis limits · ARCH-04 service layer · ARCH-05 resume · SEC-05 SSO hardening · AWS dev/staging/prod via the pipeline · QA-04/05 E2E breadth + DAST + k6 · SCIM/silo roadmap.

---

## 10. Method notes and limitations of this audit

- Static review of the repository plus execution of lint/type/unit suites; **no dynamic testing against the live pilot** (no credentials were used, nothing was deployed).
- Database-backed tests (177) and the compose/E2E stack could not run in this sandbox; the audit relies on CI history for those.
- Infrastructure code (`infra/cdk`) was reviewed for posture (KMS, private subnets, removal policies, WAF rules, OIDC deploy role) rather than line by line.
- Findings are prioritised for a medtech B2B SaaS with EU data residency; a pure research prototype would weigh §7 higher and §3–5 lower.
