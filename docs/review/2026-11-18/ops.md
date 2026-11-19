# Ops and delivery review - mgr-ibm (HEAD f704a8f = origin/main)

Scope: .github/workflows, deploy/*, infra/cdk, tools/*, justfile, health/shutdown/reaping,
backup/restore drill, OTel, EU allowlist, secrets, pinning, coverage gates, STATUS accuracy,
test-suite gaps. Read-only; nothing was modified, deployed, or sent to a cloud API.

## Strengths

- All GitHub Actions are pinned to commit SHAs, `permissions: contents: read` is the default,
  `persist-credentials: false` is set nearly everywhere, and AWS access uses GitHub OIDC with
  no long-lived keys (`.github/scripts/aws-oidc.sh` masks the credentials).
- The docs-only fast path (`tools/ci_docs_only.py`) is fail-safe and uses job-level `if:`, so
  required checks never stay pending. Isolation, static, tests, contract and security always run.
- Integration fixtures **fail** rather than skip when no database is available
  (`packages/py/testing/src/bomagent_testing/fixtures.py:39,45`), so the blocking isolation job
  cannot go green by skipping. 48 isolation tests are collected under `-m isolation`.
- EU guard: the gateway config is rendered from the catalogue at build time and fails closed
  (`eu_guard`). The CI `llm-gateway` job renders the shipped catalogue. The ECS Bedrock policy is
  limited to `aws:RequestedRegion` and the SCP to EU regions plus the WAF stack in us-east-1 only.
- The all-in-one image is built, bootstrapped, migrated and served in PR CI
  (`pr.yml:155-196`). The Postgres queue has real consumer tests
  (`tests/services/test_queue_backend.py`).
- Secret handling in operator scripts is careful: `tools/pilot-llm-key.sh` refuses `set -x`,
  reads the master key silently, and passes keys only over stdin.
- Worker robustness: `consume_forever` survives receive errors. Final run status writes are
  guarded by `status = 'running'` (`handler.py:394-396`), and takeover is a compare-and-swap on
  `started_at`.
- The restore drill's safety model works: it uses scratch-only names, a confirmation argument,
  never drops a database it did not create, and offers a dry run.

## Issues

### Critical

None verified.

### Important

**I1. Restore drill can never verify a real dump (`audit.verify_chain` called without a tenant context)**
- Where: `tools/restore_drill.py:129-134`. The function definition is in
  `packages/py/db-migrations/src/bomagent_migrations/versions/0001_foundation.py:140-154`.
- What: `verify_chain(p_tenant)` raises `insufficient_privilege` unless
  `p_tenant = app.current_tenant_id()`, which reads the GUC `app.tenant_id`. The drill calls
  `SELECT ... FROM audit.verify_chain('<tid>')` in a fresh `psql -c` session and never sets
  `app.tenant_id`.
  - With at least one tenant, every call errors. The `CalledProcessError` handler then prints
    "restore FAILED verification".
  - With zero tenants it returns `EXIT_OK` ("restore verified"). The row counts are printed but
    never asserted, so an empty or wrong dump passes. Under `--no-owner` and FORCE RLS, a
    non-BYPASSRLS admin also sees 0 rows in `tenancy.tenants`, which leads to the same false pass.
- Why it matters: this is the only backup-verification tool (runbook `backup-restore-dr.md` §3,
  monthly drill, measured RTO). The first real drill fails for a reason unrelated to the backup,
  and a broken backup can pass. The unit tests (`tests/tools/test_restore_drill.py`) only cover
  refusals and dry runs, so they cannot catch this.
- Fix:
  - Run each tenant check in one session:
    `BEGIN; SELECT set_config('app.tenant_id', '<tid>', true); SELECT ... FROM audit.verify_chain('<tid>'); COMMIT;`
    (psql `-c` with multiple statements, or `-f`).
  - Fail when `tenancy.tenants` has 0 rows unless `--allow-empty` is given.
  - Assert that `audit.events` count is greater than 0 when tenants exist.
  - Add one integration test (marker `integration`) that migrates, creates a tenant with an
    audit event, runs `pg_dump -Fc`, and runs the drill end to end.
- Owner-reserved: no (`tools/`). The fix touches nothing in migrations.

**I2. The LLM gateway image now listens on IPv6 only, which breaks the AWS (primary) path, and CI never starts the image**
- Where: `deploy/docker/llm-gateway.Dockerfile:34`
  (`CMD [..., "--host", "::", ...]`, changed in #81). Consumers: ECS
  `infra/cdk/lib/compute-stack.ts:274-288` (Service Connect `http://litellm:4000`, IPv4-only VPC,
  no `ipv6` anywhere in `network-stack.ts`). Built for ECS by `.github/workflows/main.yml:289`.
- What: with a single uvicorn process, asyncio's `create_server` sets `IPV6_V6ONLY` on `::`
  sockets (verified in the Python 3 `asyncio.base_events` source). The #81 commit message itself
  confirms the effect: "Fly's checker connects over IPv4 and the gateway listens on IPv6 only".
  The change fixed Fly's 6PN network, but the same image is the ECS gateway. In the IPv4-only VPC,
  Service Connect and the clients reach it over IPv4, so every LLM call from the API, agent-worker
  and kb-indexer would get "connection refused".
- Why it matters:
  - Nothing catches it. The ECS gateway task has no container `healthCheck` (no `healthCheck`
    in `compute-stack.ts` besides the ALB one at :410). The circuit breaker only sees crashes.
  - PR CI only *builds* the image (`pr.yml:214-215`). The compose stack uses the stock LiteLLM
    image with its own config.
  - The post-deploy smoke never calls the gateway (see I6).
  - It is latent only because `AWS_DEPLOY_ENABLED` is off.
- Fix:
  - Keep the Dockerfile default host-agnostic: `0.0.0.0`, or read the host from an env var
    `GATEWAY_HOST` with an entrypoint wrapper.
  - Set `::` only for Fly: `[processes]`/`[experimental] cmd` or `[env]` in
    `deploy/supabase/gateway.fly.toml`.
  - Add a container `healthCheck` (`/health/liveliness`) to the ECS gateway task.
  - Add a CI step that `docker run`s the built gateway image and curls
    `http://127.0.0.1:4000/health/liveliness`.
- Owner-reserved: **yes** (`deploy/docker`, `deploy/supabase`, `infra/`).

**I3. Graceful shutdown of the all-in-one (Fly pilot) is defeated by open SSE streams**
- Where: `services/all-in-one/src/bomagent_allinone/__main__.py:33-43` (no
  `timeout_graceful_shutdown`), `app.py:342-356` (workers stopped only in lifespan shutdown),
  `services/api/src/bomagent_api/routers/runs.py:144-171` (SSE up to `sse_timeout_s = 900`),
  `deploy/supabase/fly.toml:10` (`kill_timeout = "60s"`).
- What: on SIGTERM, uvicorn 0.54 first waits for all open connections. It waits forever when
  `timeout_graceful_shutdown` is None (verified in `uvicorn/server.py:281-311`). Only then does it
  run lifespan shutdown, which calls `workers.stop()`. Any browser with the live-progress view
  open holds an SSE connection for up to 15 minutes. Fly then SIGKILLs at 60 s, so
  `workers.stop()` never runs.
  - During those 60 s, `_stop` is not set, so the consumers keep claiming new messages.
  - The fly.toml comment ("workers finish the current message (30 s grace)") does not hold
    exactly when runs are being watched.
- Why it matters: every deploy or restart with an active user kills in-flight runs abruptly and
  can strand freshly claimed messages (see I4 for what happens to them).
- Fix:
  - Pass `timeout_graceful_shutdown` (for example 15 s) to `uvicorn.run`.
  - Set the workers' stop event from a SIGTERM hook rather than only in lifespan teardown, for
    example a custom `uvicorn.Server` subclass whose `handle_exit` also sets `workers._stop`.
  - End SSE generators on shutdown by checking an app-level shutting-down flag in the loop.
  - Apply the same to the separate services' `__main__.py`.
- Owner-reserved: partly (`fly.toml` comment). The code fix is not reserved.

**I4. Interrupted runs wait an hour for redelivery and then race the reaper (resume rarely wins)**
- Where:
  - `packages/py/platform-common/src/bomagent_common/messaging.py:321` and
    `infra/cdk/lib/data-stack.ts:203`: runs visibility timeout 3600 s.
  - `services/api/src/bomagent_api/app.py:169-170` and
    `services/api/src/bomagent_api/maintenance.py:38-56`: reaper fails `running` runs after
    `started_at + 3600 s`, checked every 30 s.
  - `services/all-in-one/src/bomagent_allinone/app.py:328-339`: cancelled handlers do not
    release their message.
  - `compute-stack.ts:497-505`: no `stopTimeout` on worker containers, so the ECS default of 30 s
    applies.
- What: a worker stopped mid-run, whether by a deploy or by I3, leaves the message invisible
  until `receive_time + 3600 s`. The reaper fails the run at `started_at + 3600 s`, and
  `started_at` is about the receive time. The redelivery that would trigger the checkpoint
  takeover (`handler.py:164-200`) and the reaper therefore become due within the same ~30 s
  window, about an hour later. Whichever comes first wins. Variant A calls can take up to 915 s
  each (#83), so a 30 s ECS stop timeout interrupts almost every in-flight run on every deploy.
- Why it matters: the resume feature is in practice a coin flip, delayed by an hour. Users see
  runs hang for 60 minutes and then fail after every deploy.
- Fix:
  - On cancellation, release the message (`ChangeMessageVisibility` to about
    `resume_stale_after_s`, or the PostgresQueue equivalent) instead of waiting out the full
    visibility timeout.
  - Make the reaper threshold clearly larger than visibility timeout plus resume threshold, or
    base it on the last checkpoint time rather than `started_at`.
  - Set `stopTimeout: Duration.seconds(120)` (the Fargate maximum) on the worker containers.
  - Add a test that simulates a mid-run cancel and asserts the run resumes rather than being
    reaped.
- Owner-reserved: `infra/` part yes. The code part is no.

**I5. The AWS deploy rolls out new application images before running migrations**
- Where: `tools/deploy.sh:41` (`cdk deploy --all`, which updates every ECS service to
  `IMAGE_TAG`) runs before `deploy.sh:66-67` (`run_task DbBootstrapTaskDefinition`,
  `MigrationTaskDefinition`).
- What: new code serves traffic against the old schema until the migration task finishes. If the
  migration fails, the services stay on the new image with the old schema. The ALB health check
  is `/healthz` (no DB), so the circuit breaker does not roll back. This is the opposite of the
  Fly path (`release_command` runs before the release) and of the expand/contract assumption in
  `runbooks/rollback.md`, where the old code tolerates the new schema, not the reverse.
- Fix: deploy the migrate task definition first, run the migration, then `cdk deploy --all`.
  Two ways to do that:
  - Put bootstrap and migrate in their own stack, deploy it, run the tasks, then deploy the rest.
  - Or deploy Compute with only the migrate image bumped.
- Owner-reserved: **yes** (deployment pipeline; `tools/deploy.sh` is invoked by
  `deploy-env.yml`).

**I6. Post-deploy smoke checks only liveness; TESTING.md smoke steps 2-7 do not exist anywhere**
- Where: `tests/smoke/test_smoke.py` has only health/readiness, gateway liveliness and the Tempo
  trace. That is TESTING.md steps 1 and 8. `tools/deploy.sh:87-92` only checks `GET /` and
  `/v1/me` == 401. `.github/workflows/smoke.yml:99` runs only the API health test and succeeds
  as a no-op when the secret is missing (`smoke.yml:81-83`).
- What: login, upload to `parsed`, a variant B run to `completed` with more than 0 items, CSV
  export, the audit event, and the `smoke-b` 404 are all missing from the smoke suite. (E2E covers
  similar paths in compose only.)
- Why it matters: a deployment that is healthy but cannot run anything passes. I2 is exactly that
  case. TESTING.md requires these after every deployment.
- Fix:
  - Add smoke tests for steps 2-7, parametrised by `SMOKE_API_KEY`.
  - Run them from `deploy.sh` (or a job after `deploy-env`) and from `smoke.yml`.
  - Have `smoke.yml` fail, not succeed, when invoked without the secret, because it is
    manual-only anyway.
- Owner-reserved: `tools/deploy.sh` yes. The tests and workflow are no.

**I7. Coverage gates do not enforce TESTING.md thresholds**
- Where: `tools/check_coverage.py:13-39`, `pr.yml:75-76`, `apps/web/package.json:10` and
  `packages/ts/*/package.json` (`vitest run`, no coverage).
- What:
  - (a) There is no frontend coverage gate, although TESTING.md requires at least 75 %.
  - (b) "No drop in coverage in a PR" is not checked: there is no baseline comparison.
  - (c) The thresholds are aggregated over all of `packages/py` and all of `services`, so one
    package far below 85 % hides behind the others. TESTING.md says `packages/py/*`.
  - (d) The gate returns 0 when no file matches. Verified: an empty Cobertura report exits 0, so
    a misconfigured `--cov` source passes silently.
- Fix:
  - Compute coverage per package (`packages/py/<name>`, `services/<name>`).
  - Fail when a group has 0 lines.
  - Add `vitest --coverage` with `thresholds: { lines: 75 }` for `apps/web` and `packages/ts/*`.
  - Compare against the base branch's `coverage.xml` artifact, or add a `diff-cover` step.
- Owner-reserved: `.github/` is under CODEOWNERS, but it is not a deploy, migration or auth file.

**I8. The nightly evaluation defaults to a disabled, unverified model**
- Where: `.github/workflows/nightly-evals.yml:17,46` (`claude-sonnet-eu`) and
  `packages/py/llm/src/bomagent_llm/catalog/models.yaml:146-157` (`enabled: false`,
  `verified: false`).
- What: `bomagent_cli.main.build_chat` raises `ModelNotAllowedError` for unverified models
  (asserted in `packages/py/cli/tests/test_cli.py:152-158`). Once the owner sets the
  gateway secrets, every scheduled run fails on every sample for a config reason, not a quality
  regression. The only enabled real model is `mistral-large-eu`.
- Fix: default to `mistral-large-eu`, or read the default from the catalogue's first
  enabled+verified non-fake chat model. Add a unit test that the workflow default is an enabled,
  verified catalogue id.
- Owner-reserved: no.

**I9. EU egress allowlist is not enforced at the network layer; API and agent-worker have unrestricted egress**
- Where: `infra/cdk/lib/compute-stack.ts:340` (`ApiSg` default `allowAllOutbound`), `:472`
  (`allowAllOutbound: !isolated` for agent/kb workers), and the gateway SG (default). NAT without
  filtering (`network-stack.ts:66`).
- What: ARCHITECTURE.md §network and CLAUDE.md rule 2 ("No endpoints outside the allowlist")
  call for an egress domain allowlist. Today every task in the app subnets can reach any internet
  host. The EU guarantee rests only on the gateway catalogue. DECISIONS_LOG 2026-11-10 records
  "NAT without domain filtering", pending owner acceptance, but that row is about LLM providers.
  It does not cover the API and agent-worker, which process untrusted file content.
- Fix: Route 53 Resolver DNS Firewall (cheap) with an allowlist of the gateway's provider hosts,
  Cognito/IdP JWKS hosts and AWS endpoints, applied to the VPC. Tighten `ApiSg` and the
  agent/kb SGs to 443 towards the gateway SG, the VPC endpoints and the IdP. Alternatively, write
  an ADR that accepts the gap explicitly.
- Owner-reserved: **yes** (`infra/`).

### Minor

- **M1. `docs/STATUS.md` drifts from the code:**
  - `:169` says "Automatic resume of a crashed run ... is not wired (the reaper fails stuck
    runs)", but resume and takeover are implemented
    (`services/agent-worker/src/bomagent_agent_worker/handler.py:14-16,164-200`, `max_resumes`).
  - `:10` says "The pilot still runs on the fake model", which #81 changed
    (`BOMAGENT_ALLOW_FAKE_LLM` removed from `fly.toml`).
  - #81-#83 (gateway on 6PN, Mistral fixes, timeouts and the 1200 s resume threshold) are not
    recorded.
  - `:42` points to `deploy/observability/`, which does not exist.
  - Fix: update STATUS with a 2026-11-18 entry and delete the stale limitation.
  - Not owner-reserved.
- **M2. The isolation marker covers only DB-level tests.** The API cross-tenant 404 checks
  (`services/api/tests/test_api_flow.py:240,244,420,439`) and the object-store tenant-prefix
  guard (`packages/py/platform-common/tests/test_storage.py:43`) are not `isolation`, so they are
  outside the "tenant isolation (blocking)" required check that STATUS asks the owner to protect.
  TESTING.md lists API, SQL, S3, KB and events for that suite. Fix: add `pytest.mark.isolation`
  to those tests.
- **M3. Base images and helpers are referenced by mutable tags** (`python:3.12-slim-bookworm`,
  `node:22-bookworm-slim`, `ghcr.io/astral-sh/uv:0.11` in all three Dockerfiles; ZAP
  `ghcr.io/zaproxy/zaproxy:stable` at `dast-zap.yml:234`), and no cosign signing despite
  SECURITY.md. The Dockerfile comments say "pin by digest when a pipeline builds this image", and
  `main.yml` now does build them. This is acknowledged in `runbooks/supply-chain-pinning.md`.
  Owner-reserved: **yes** (`deploy/docker`).
- **M4. `smoke.yml`** uses `runs-on: ubuntu-latest` (`:71`, everything else is pinned to
  `ubuntu-24.04`), and its checkout (`:90`) lacks `persist-credentials: false`.
- **M5. The arm64 images that `main.yml:278,307` pushes are never built in PR CI** (PR builds are
  amd64 only). An arm64-only build break surfaces only on `main` during a deploy. Fix: add
  `--platform linux/arm64` to one PR build, or use an `ubuntu-24.04-arm` runner.
- **M6. Missing health checks:**
  - The Fly gateway has none: it was dropped in #81, `gateway.fly.toml:24-29`.
  - No ECS task container `healthCheck` for the gateway or the workers. ECS ignores the
    Dockerfile `HEALTHCHECK`.
  - Worker readiness in the separate services does not include "consumer task alive" (only the
    database). The all-in-one does include it.
  - Fix: a container `healthCheck` on `/readyz` that includes consumer liveness.
  - Owner-reserved: **yes** for `deploy/`, `infra/`.
- **M7. OTel is not exported in the AWS path.** No `BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT` and no
  ADOT collector in `infra/cdk/lib/` (acknowledged as "planned" in `docs/platform/AS_BUILT.md:30`,
  ADR-0010). TESTING.md smoke step 8 is therefore impossible in the cloud. Owner-reserved:
  **yes** (`infra/`).
- **M8. `tools/restore_drill.py:84`** passes the admin URL, password included, as a `psql`/
  `pg_restore` argv element. It is visible in `ps` on shared hosts, which contradicts the
  docstring's intent ("connection strings come from the environment"). Fix: split the URL into
  `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` env vars for the subprocess.

## Declined to judge

- Branch protection and required checks on GitHub: not visible from the repo. Merge gating of
  `main.yml` relies on it, because the deploy does not depend on the `pr.yml` run for the same
  commit.
- Whether the Fly LiteLLM gateway has the database that `/key/generate` virtual keys need
  (`DATABASE_URL` would be a Fly secret, not visible here).
- Whether variant A runs on Mistral Large legitimately exceed the 3600 s reaper or visibility
  window without any interruption. Measured run durations were not available.
- Which role the backup runbook's `pg_dump` uses, and whether it can dump FORCE-RLS tables.
- The current Trivy, CodeQL and Bandit findings (not run here), and the correctness of the
  catalogue's `license_class` values (outside ops).
