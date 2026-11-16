# Audit implementation progress

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
| OPS-01 OTel endpoint wiring, alert rules, uptime/error-tracking config | todo | | | Grafana/Sentry accounts = owner |
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
| TH-03 dataset ingestion with double verification | needs owner | | | data collection, licences, verification = owner; code side: SOURCE/verification templates, agreement metric |
| TH-06 extra error classes in validation experiment | in PR (injector + reporting); config wiring now unblocked (#32 merged) | claude/audit-th-06 | | this PR: `BEYOND_RULES_KINDS` (wrong plausible MPN, wrong tolerance, voltage derating, obsolete part) that `core@1.0.0` cannot see, `rule_coverage()`, false alarms per rule; default mix unchanged; `injection.kinds` in experiment config + report tables = follow-up (touches `experiment.py`) |
| TH-04 pre-registration, Holm, cluster bootstrap, effect sizes | todo | | | |
| Run the matrix, chapter 7 figures | needs owner | | | needs real models + dataset |

## Phase 2 - first paying pilot customer

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| SEC-02 BFF session + CSP tightening | todo | | | touches web session handling / auth: PR stays open for owner |
| SEC-15 onboarding SECURITY DEFINER function | todo | | | migration/RLS: PR stays open for owner |
| SEC-06 MFA (aal2 / amr checks) | todo | | | enabling MFA in Supabase console = owner; auth/authz change: PR stays open |
| SEC-14 export / delete / retention / sub-processors | todo | | | migration likely: PR stays open; DPAs = owner |
| UX-02 e-mail invitations | todo | | | SMTP provider account = owner |
| UX-03 lifecycle actions (delete, cancel, history, XLSX) | todo | | | |
| SEC-09 malware scan | todo | | | GuardDuty / ClamAV sidecar deploy = owner |
| OPS-04 migration policy, rollback runbook, smoke | todo | | | |
| OPS-05 backups / DR runbook + restore drill script | todo | | | paid Supabase plan = owner |
| OPS-06 runbooks | todo | | | |
| SEC-10 supply chain (digests, Trivy image, license gate, SAST) | todo | | | cosign in deploy.sh touches `deploy/*` |
| QA-02 cassette recorder, nightly real-model eval workflow | todo | | | secrets in GitHub environment = owner |
| ARCH-06 KB snapshot per run | todo | | | |

## Phase 3 - scale and enterprise

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| ARCH-03 LISTEN/NOTIFY, indexes, outbox relay query | todo | | | |
| ARCH-04 service layer | todo | | | |
| ARCH-05 resume from checkpoints | todo | | | |
| SEC-05 SSO hardening | todo | | | touches sso.py: PR stays open for owner |
| AWS dev/staging/prod via the pipeline | needs owner | | | deployment is a human step |
| QA-04 E2E breadth, QA-05 DAST | todo | | | |
| OPS-09 k6 scenarios, capacity note | todo | | | |
| SCIM / silo roadmap | skipped | | | roadmap item, no code in this pass |

## Phase 4 - remaining audit items (not in section 9)

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| SEC-07 Supabase custom access token hook | todo | | | hook activation in Supabase = owner |
| SEC-11 docs/openapi off outside dev | todo | | | |
| SEC-12 injection corpus, canary, free-text sanitising | todo | | | |
| SEC-16/17 low items (CODEOWNERS, SECURITY.md, idempotency TTL, parser error leak test) | todo | | | branch protection = owner |
| ARCH-01 deployment tiers ADR | merged as draft ADR-0018 (Proposed) | claude/audit-doc-02 | #25 | acceptance = owner |
| ARCH-07 embeddings status in readyz | todo | | | |
| ARCH-08 wire eu_guard check_environment at gateway start | todo | | | |
| ARCH-09 / DOC-01 as-built section, status files cleanup | todo | | | |
| ARCH-10 symlink removal, CHANGELOG, tags | todo | | | |
| OPS-03 bomagent-ops CLI | todo | | | |
| OPS-07 CI cost / path filters | todo | | | |
| OPS-08 migration lint + downgrade test | todo | | | |
| DATA-01 / DATA-02 indexes, TTL sweeps, re-index doc | todo | | | indexes need a migration: PR stays open |
| QA-03 property tests | todo | | | |
| UX-04 BOM table sort/filter/virtualise | todo | | | |
| UX-05 localised error messages | todo | | | |
| UX-06 focus management | todo | | | |
| UX-07 quota chips, checklist | todo | | | |
| UX-08 a11y regression gate | todo | | | |
| DOC-03 LICENSE / legal drafts | needs owner | | | licence choice and legal review = owner |
| DOC-04 just doctor, CONTRIBUTING | todo | | | |
| TH-07 Agent SDK arm decision | needs owner | | | scope decision = owner |
| TH-08 appendices generation | todo | | | |
| TH-09 experiment status page | todo | | | |
