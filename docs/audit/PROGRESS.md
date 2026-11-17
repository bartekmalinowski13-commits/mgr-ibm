# Audit implementation progress

## Final report (2026-11-17)

**Merged by me (squash, CI green):** #18-#27, #29-#36, #38-#52, #62, #64-#70 (about 55 PRs; the list in the table below has the item behind each). All audit items that did not need the owner are merged at least in their code part.

**Open PRs waiting for the owner (not merged on purpose):**
- #28 Fly process groups, Grafana dashboards, alert rules (`deploy/*`).
- #37 gateway refuses to start on a non-EU environment (`deploy/*`; image start not run here).
- #55 draft: downgrade round-trip test, fails today because the SSO revision's `downgrade()` is broken (needs a migration fix).
- #71 SEC-06 step-up MFA (`auth.py`/`authz.py`), #72 migrations bundle SEC-15/SEC-07/DATA-01/02 (SECURITY DEFINER onboarding, indexes), #73 SEC-05 SSO hardening + SEC-03 part 2 (`sso.py`; web and API deploy together). #71 and #73 both touch `auth.py`/`app.py`: expect a small conflict on the second merge.

**Not started:** SEC-02 (BFF session + CSP; wait for #71/#73), ARCH-03 LISTEN/NOTIFY, `runs.trace` cap, SQL still in six routers (ARCH-04), OPS-01 error tracking (new dependency, decide first).

**Owner to-do list, in priority order**
1. Review and merge #37 and #28, then `fly deploy` and check `fly status` (one `web`, one `worker`). Nothing from this audit is deployed: I never deploy (CLAUDE.md rule 6).
2. Review #72 (migrations, RLS-adjacent), #71, #73 and fix the SSO downgrade (#55). Deploy #73's web and API together.
3. Branch protection on `main` with the `tenant isolation (blocking)` check; then required checks and auto-merge are safe. Enable GitHub private vulnerability reporting.
4. Accounts and keys: Grafana EU + OTLP token + uptime probe, error-tracking decision (Sentry/GlitchTip), write-once bucket for audit anchors (`BOMAGENT_AUDIT_ANCHOR_*`), mail provider + SPF/DKIM + `BOMAGENT_SMTP_*`, clamd for uploads, Supabase hook + TOTP enrolment, backup plan (PITR, EU bucket, first restore drill), CloudFront header + `BOMAGENT_CLIENT_IP_HEADER` on AWS, `nightly-evals` and `smoke` environments with their secrets.
5. Models: real prices from provider lists (TH-05), model access, flip `enabled`/`verified`, real cassettes, thresholds for the nightly run.
6. Thesis: freeze `docs/thesis/PREREJESTRACJA.md` (tag `prereg-v1`), ingest at least six real open designs with two independent verifiers (TH-03), then run the matrix.
7. Decisions: accept or reject the pending rows in `docs/DECISIONS_LOG.md` (about 70, `tools/decisions_pending.py` lists them), ADR-0017/0018, IP retention in the audit log, RPO/RTO, sub-processor facts (`docs/legal/`), DOC-03, TH-07.
8. Housekeeping: rotate the LLM master key if it was ever used as an app key, delete `~/.mgr-ibm-llm-secrets.env` and `~/.mgr-ibm-pilot-secrets.env`, smoke-test a multipart upload above 8 MiB on Supabase, set `.python-version` to 3.12.

**Caveats you should know:** DB-backed tests only run in CI; several PRs could not run them locally. The image start of #37, the restore drill script, the ZAP/Trivy/Bandit workflows and the mobile E2E spec have never run against real infrastructure. Items marked "merged" often mean the code part only. Process slips: #45 was merged on a "no failing suite" event before I read `mergeable_state` (checked afterwards, main is green), and #70 (a 2.4k-line refactor) merged without a separate reviewer pass.



Source: [`FABLE_AUDIT_EN.md`](FABLE_AUDIT_EN.md) (order of work: section 9).
Maintained by the implementation session; one row per task. Status values:
`todo` / `in progress` / `in PR` / `merged` / `needs owner` / `skipped`.
"needs owner" rows still get their code side (runbook, script, flagged migration) where one exists;
the Notes column says what the owner must do.
PRs touching RLS policies, migrations, `auth.py`, `authz.py`, `sso.py`, web session handling or
`deploy/*` stay open for the owner (status `in PR, needs owner`).

Scheduled task `audit-implementation-continue` (hourly, id `trig_0174gXcCFuTekwmbAvZAoULc`) exists and is enabled; it was created from the parent session. Disable it with `update_trigger` when all doable work is done.

## Phase 0 - before any real user data on the pilot

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| UX-01 demo banner + watermark | merged | claude/audit-ux-01 | #18 | demo detected only in `services/all-in-one` (DECISIONS_LOG) |
| SEC-03 per-IP limits, SSO discovery as POST | merged (part 1); part 2 todo | claude/audit-sec-03 | #19 | part 1 (in-memory per-IP buckets, `ip_limits.py`) in this PR; part 2 (discovery as POST, touches routers/sso.py + web) queued as a separate PR for the owner; Fly/Supabase console limits = owner; AWS: forward `CloudFront-Viewer-Address` + set `BOMAGENT_CLIENT_IP_HEADER` (CDK, owner PR) |
| SEC-13 presigned uploads, parse semaphore | merged (streaming part) | claude/audit-sec-13 | #20 | this PR: streamed uploads (chunked hash, `ObjectStore.put_file`, no 64 MiB `bytes`); ingest already takes one message at a time per worker; presigned PUT + `files/complete` deferred: needs bucket CORS for the SPA origin on Supabase Storage/S3 (owner) |
| SEC-01 parser isolation (no-new-privs, rlimits, netns) | merged (code part) | claude/audit-sec-01 | #21 | this PR: child sets no_new_privs, NOFILE 32, FSIZE 0, empty netns when allowed (reported in logs); separate Fly app / no-egress parser group = ARCH-02 deploy PR (owner); AWS ingest IAM/ABAC = CDK (owner) |
| ARCH-02 process groups | merged (code, #27); fly.toml in PR #28 = in PR, needs owner | claude/audit-arch-02 | #27, #28 | code: `BOMAGENT_ROLE=all|web|worker`; `deploy/supabase/fly.toml` process groups + dashboards/alerts in #28 (deploy/*, left open for owner) |
| OPS-01 OTel endpoint wiring, alert rules, uptime/error-tracking config | alerts + dashboards in #28 (needs owner); error tracking todo | | #28 | Grafana/Sentry accounts = owner; Sentry/GlitchTip SDK = new dependency (supply chain, SEC-10) - needs an owner decision before code |
| OPS-02 OTel metrics + dashboards JSON | merged (code); dashboards/alerts todo (deploy/*, owner PR) | claude/audit-ops-02 | #22 | this PR: metrics module + instrumentation (runs, LLM usage/cost, parse, outbox/queue dead-letters) + OTLP metrics export; dashboards JSON under `deploy/observability/` = separate PR (deploy/*, owner); queue depth/age gauges later (OPS-03) |
| SEC-04 source IP in audit, anchor export job | merged (#23, #24); partitioning + user agent = migration (owner PR) | claude/audit-sec-04b | #23, #24 | this PR: source IP in every API-written audit event (request-scoped, validated, from the trusted edge header); user agent needs a column = migration (owner PR); this PR (part 2): daily per-tenant anchor export to a write-once sink (`BOMAGENT_AUDIT_ANCHOR_DIR` or `BOMAGENT_AUDIT_ANCHOR_BUCKET` [+ `_ENDPOINT_URL`]), `verify` compares against stored anchors; partitioning = migration (owner PR); OWNER: create the Object Lock bucket (AWS) / write-once bucket + second off-platform copy (pilot) and set the env vars |
| DOC-02 decision-log acceptance helper, ADR-0017/0018 drafts | merged (code side); acceptance = needs owner | claude/audit-doc-02 | #25 | Acceptance of DECISIONS_LOG rows and ADRs = owner; code side: ADR-0018 draft, nightly staleness check |
| SEC-08 virtual keys, rotation runbook | merged | claude/audit-sec-08 | #26 | this PR: `tools/pilot-llm-key.sh` (virtual key create/rotate/delete, secrets never on argv/disk), vault file dropped from `pilot-llm-setup.sh`, `key-rotation.md`; OWNER: run the script, rotate the master key if it was ever used as app key, delete `~/.mgr-ibm-llm-secrets.env` and `~/.mgr-ibm-pilot-secrets.env` after saving to the password manager |

## Phase 1 - thesis experiment (code-only items)

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| TH-05 catalogue prices with date/source, manifest model ids, temperature/seed notes | merged (code, #31); prices/access needs owner | claude/audit-th-05 | #31 | real prices/model access from provider consoles = owner |
| TH-02 Postgres retriever in the experiment, manifest fields | merged (manifest part, #32); `--retriever postgres` todo | claude/audit-th-02 | #32 | this PR: manifest `retrieval` block (retriever, embedding, reranker, `kb_snapshot_id` content hash) + limitation note in METODYKA; postgres retriever needs a DB (CI-only tests) |
| TH-01 attempted-hallucination metric, METODYKA note, A-unguarded ablation | merged (metric + note, #29); ablation todo | claude/audit-th-01 | #29 | metric `attempted_mpn_hallucination_rate` in eval summary, experiment tables/figure, `docs/thesis/METODYKA.md`; A-unguarded ablation = follow-up |
| TH-03 dataset ingestion with double verification | merged (tooling, #36); dataset ingestion needs owner | claude/audit-th-03 | #36 | this PR: `bomagent_eval.agreement` (per-field agreement + Cohen kappa between two verifiers) and `bomagent_eval.dataset` (SOURCE.md validation, two distinct verifiers for real designs, size strata, control vs real); ingesting >= 6 real designs and the two human verifications = owner |
| TH-06 extra error classes in validation experiment | merged (#33 injector, this PR config + report) | claude/audit-th-06b | #33 | `injection.kinds` in the experiment config, `rule coverage` column and false alarms per rule in the report, `rule_covered` in `detection_by_kind.csv` |
| TH-04 pre-registration, Holm, cluster bootstrap, effect sizes | merged (#35); freezing the pre-registration = owner | claude/audit-th-04 | #35 | `holm_adjust`, `cluster_bootstrap_ci`, `effect_size` (d_z) in `experiment_stats`; primary family (line F1, attempted hallucination, cost) in the report and `paired.csv`; the note must be frozen (tag `prereg-v1`) by the author before the first real-model run |
| Run the matrix, chapter 7 figures | needs owner | | | needs real models + dataset |

## Phase 2 - first paying pilot customer

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| SEC-02 BFF session + CSP tightening | not started (needs owner) |  |  | BFF session + CSP touches auth.py and apps/web session handling that #71/#73 also change; start after those are decided |
| SEC-15 onboarding SECURITY DEFINER function | in PR #72, needs owner (migration, RLS) | claude/audit-migrations-bundle | #72 | revision 0015: SECURITY DEFINER `tenancy.create_organization`; platform role loses INSERT on tenants and all access to memberships; isolation test + downgrade round trip for 0015/0016 |
| SEC-06 MFA (aal2 / amr checks) | in PR #71, needs owner (auth.py/authz.py) | claude/audit-sec-06 | #71 | step-up MFA behind `BOMAGENT_MFA_ENFORCED` (off by default), 403 `mfa-required`, top-level aal/amr only; owner enrols TOTP in Supabase then turns it on; web step-up UI and Cognito not done |
| SEC-14 export / delete / retention / sub-processors | partial (export + legal docs, #67); delete/retention/MFA = owner | claude/audit-sec-14 | #67 | `POST /v1/organizations/{id}/export` (async ZIP, signed link, rate limited, audited, tenant-isolation test), SUBPROCESSORS.md, DPA_CHECKLIST.md; not done: org hard delete, retention sweeps, export file expiry, in-app legal link |
| UX-02 e-mail invitations | merged (backend, #48); web landing + resend todo | claude/audit-ux-02 | #48 | mailer protocol (log default, SMTP via env, TLS always), invitation e-mail PL+EN, audited; owner: mail provider, SPF/DKIM, env vars. Note: `LogMailer.sent` is unbounded when SMTP is off |
| UX-03 lifecycle actions (delete, cancel, history, XLSX) | merged (#66) | claude/audit-ux-03 | #66 | project rename/delete, file delete, run cancel/re-run, BOM version history + diff, XLSX; cancelled run stored as `failed` ("cancelled by user") until a migration adds a status |
| SEC-09 malware scan | merged (code, #46); running clamd = owner | claude/audit-sec-09 | #46 | scanner protocol, EICAR default, optional clamd (fail closed), audit + metrics; GuardDuty S3 / quarantine not done |
| OPS-04 migration policy, rollback runbook, smoke | merged (#64); Fly 2 machines + smoke tenant = owner | claude/audit-ops-04 | #64 | expand/contract policy, `drop-table` / `contract-mixed` lint rules, rollback runbook, manual smoke workflow (secret by name) |
| OPS-05 backups / DR runbook + restore drill script | merged (script + runbook, #45); drills = owner | claude/audit-ops-05-06 | #45 | `tools/restore_drill.py` (scratch DB only), backup-restore-dr runbook with proposed RPO/RTO; owner: PITR plan, backup bucket, first real drill. Script never run on a real Postgres |
| OPS-06 runbooks | merged (#45) | claude/audit-ops-05-06 | #45 | incident, breach (72 h), offboarding, on-call, capacity runbooks; owner: contact details. `docs/platform/SECURITY.md` still links `docs/runbooks/` (needs a docs(spec) fix) |
| SEC-10 supply chain (digests, Trivy image, license gate, SAST) | merged (#65, report-only); digests/cosign/SBOM = owner | claude/audit-sec-10 | #65 | licence gate (AGPL/SSPL), Trivy image scan x3, Bandit; none required yet; digest pinning checklist in the runbooks (deploy/docker is owner-reserved) |
| QA-02 cassette recorder, nightly real-model eval workflow | merged (code, #44); real recordings + nightly secrets = owner | claude/audit-qa-02-03 | #44 | `RecordingChat`, `bomagent record`, `run --min-f1/--max-hallucination-rate`, secret-gated nightly workflow |
| ARCH-06 KB snapshot per run | merged (#69) | claude/audit-arch-06 | #69 | every API run and re-run is pinned to a tenant KB snapshot (existing column, no migration); shown on the run page and in CSV/XLSX exports |

## Phase 3 - scale and enterprise

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| ARCH-03 LISTEN/NOTIFY, indexes, outbox relay query | partial (runs index in #72) | claude/audit-migrations-bundle | #72 | LISTEN/NOTIFY and the outbox relay query not done (behaviour risk) |
| ARCH-04 service layer | merged (#70, partial) | claude/audit-arch-04 | #70 | services + repositories for projects, runs, members, KB; import-linter contract routers > services > repositories; left: api_keys, audit, identity, sso, samples, exports routers and plans/idempotency SQL. No independent review pass was done on this refactor (covered by the DB tests in CI) |
| ARCH-05 resume from checkpoints | merged (#52, no migration); heartbeat/reaper = owner | claude/audit-arch-05 | #52 | resume from checkpoint for A and B, recorded in run record/trace/audit; `heartbeat_at` column and per-plan timeout need a migration |
| SEC-05 SSO hardening | in PR #73, needs owner (sso.py) | claude/audit-sec-05 | #73 | discovery as POST (SEC-03 part 2: web and API must be deployed together), free-mail blocklist, 8 h auth_time limit, error redaction, nonce check; not done: Cognito reconcile, TXT re-verification (migration), API key lifetime cap |
| AWS dev/staging/prod via the pipeline | needs owner | | | deployment is a human step |
| QA-04 E2E breadth, QA-05 DAST | merged (mobile spec, #50) | claude/audit-ops-08-09-qa-04-05 | #50 | phone-viewport E2E; QA-05 ZAP baseline workflow (manual/scheduled) merged; not run locally |
| OPS-09 k6 scenarios, capacity note | merged (k6 + placeholder note, #50) | claude/audit-ops-08-09-qa-04-05 | #50 | `tests/load/bomagent.js`, capacity-k6 runbook; numbers are placeholders until measured |
| SCIM / silo roadmap | skipped | | | roadmap item, no code in this pass |

## Phase 4 - remaining audit items (not in section 9)

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| SEC-07 Supabase custom access token hook | in PR #72, needs owner (Supabase dashboard) | claude/audit-migrations-bundle | #72 | hook SQL for the Supabase `postgres` database + runbook; owner enables the hook, then sets `BOMAGENT_OIDC_EMAIL_VERIFIED_CLAIM=email_verified` |
| SEC-11 docs/openapi off outside dev | merged (#38) | claude/audit-sec-11 | #38 | `Settings.docs_enabled` (local/test/dev only); contract stays in `services/api/openapi.json`; a docs-site page (Redocly/Scalar) is a follow-up |
| SEC-12 injection corpus, canary, free-text sanitising | merged (#41); remainder todo | claude/audit-sec-12 | #41 | detector fix (irregular whitespace), 16+12 corpus with a 5 % success-rate gate, `clean_free_text`; left: wire the cleaner into storage, injection success rate in `bomagent experiment`, canary in prompt, LLM classifier |
| SEC-16/17 low items (CODEOWNERS, SECURITY.md, idempotency TTL, parser error leak test) | merged (SEC-17, #39); SEC-16, auth.py comment, branch protection = owner | claude/audit-sec-17 | #39 | SECURITY.md, CODEOWNERS, idempotency TTL sweep, parser error text test |
| ARCH-01 deployment tiers ADR | merged as draft ADR-0018 (Proposed) | claude/audit-doc-02 | #25 | acceptance = owner |
| ARCH-07 embeddings status in readyz | merged (#40) | claude/audit-arch-07 | #40 | API and KB indexer refuse hashing embeddings outside local/test unless `BOMAGENT_ALLOW_FAKE_LLM` |
| ARCH-08 wire eu_guard check_environment at gateway start | in PR #37, needs owner (deploy/*) | claude/audit-arch-08 | #37 | gateway entrypoint runs the EU environment check; image start not run here |
| ARCH-09 / DOC-01 as-built section, status files cleanup | merged (#47) | claude/audit-arch-09-10 | #47 | `docs/platform/AS_BUILT.md` checked against code; HANDOFF archive + "15 ADRs" fix in STATUS.md still todo |
| ARCH-10 symlink removal, CHANGELOG, tags | partial (#47: CHANGELOG) | claude/audit-arch-09-10 | #47 | CHANGELOG done; `evals/samples` symlink kept (nightly workflow and test depend on it); tags = owner |
| OPS-03 bomagent-ops CLI | merged (skeleton, #42) | claude/audit-doc-04-ops-03-07 | #42 | `bomagent-ops env|queries` read-only; requeue/purge need RLS + audit |
| OPS-07 CI cost / path filters | merged (docs-only fast path, #42) | claude/audit-doc-04-ops-03-07 | #42 | job-level skip of heavy jobs on docs-only PRs; confirm on the next docs-only PR; caching/nightly matrix todo |
| OPS-08 migration lint + downgrade test | merged (migration lint, #50); round-trip test in draft PR #55, needs owner | claude/audit-ops-08-downgrade | #50, #55 | round-trip test found a real defect: downgrade of `tenancy.sso_domains` fails (policy dependency) - migration fix = owner |
| DATA-01 / DATA-02 indexes, TTL sweeps, re-index doc | in PR #72 (indexes, TTL), trace cap not done | claude/audit-migrations-bundle | #72 | concurrent indexes on runs/files, rate_windows TTL sweep, growth doc; `runs.trace` size cap documented only |
| QA-03 property tests | merged (#44) | claude/audit-qa-02-03 | #44 | Hypothesis tests for values, designators, grouping, CSV round trips; mutmut not added |
| UX-04 BOM table sort/filter/virtualise | merged (#51); column resize todo | claude/audit-ux-04-07 | #51 | sort/filter/virtualise/sticky/visibility/Copy CSV |
| UX-05 localised error messages | merged (#43) | claude/audit-ux-05-06-08 | #43 | 34 slugs localised PL+EN; dynamic numbers (quota) now generic |
| UX-06 focus management | merged (#43) | claude/audit-ux-05-06-08 | #43 | ItemPanel focus in/out, Tab trap, aria-live save |
| UX-07 quota chips, checklist | merged (#51, admin-only chips) | claude/audit-ux-04-07 | #51 | chips for all roles need a backend permission change (authz.py = owner) |
| UX-08 a11y regression gate | merged (#43, vitest gate) | claude/audit-ux-05-06-08 | #43 | contrast/reduced-motion/lang; Playwright axe not added |
| DOC-03 LICENSE / legal drafts | needs owner | | | licence choice and legal review = owner |
| DOC-04 just doctor, CONTRIBUTING | merged (#42) | claude/audit-doc-04-ops-03-07 | #42 | `just doctor`, CONTRIBUTING.md; static OpenAPI page todo |
| TH-07 Agent SDK arm decision | needs owner | | | scope decision = owner |
| TH-08 appendices generation | merged (code, #49) | claude/audit-th-08-09 | #49 | `bomagent experiment appendices` (A, B, C, trace table); not embedded in the docx build |
| TH-09 experiment status page | merged (#49) | claude/audit-th-08-09 | #49 | `bomagent experiment status` static page; capacitor "1M" normalisation bug fixed in the same PR |
