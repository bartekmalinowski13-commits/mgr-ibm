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
| SEC-03 per-IP limits, SSO discovery as POST | in progress | claude/audit-sec-03 | | part 1 (in-memory per-IP buckets, `ip_limits.py`) in this PR; part 2 (discovery as POST, touches routers/sso.py + web) queued as a separate PR for the owner; Fly/Supabase console limits = owner |
| SEC-13 presigned uploads, parse semaphore | todo | | | |
| SEC-01 parser isolation (no-new-privs, rlimits, netns) | todo | | | separate Fly app/AWS IAM parts = owner/deploy |
| ARCH-02 process groups | todo | | | `deploy/*` change: leave PR open for owner |
| OPS-01 OTel endpoint wiring, alert rules, uptime/error-tracking config | todo | | | Grafana/Sentry accounts = owner |
| OPS-02 OTel metrics + dashboards JSON | todo | | | |
| SEC-04 source IP in audit, anchor export job | todo | | | Object-store target/off-platform copy = owner |
| DOC-02 decision-log acceptance helper, ADR-0017/0018 drafts | needs owner | | | Acceptance of DECISIONS_LOG rows and ADRs = owner; code side: ADR-0018 draft, nightly staleness check |
| SEC-08 virtual keys, rotation runbook | todo | | | rotate real keys = owner |

## Phase 1 - thesis experiment (code-only items)

| Task | Status | Branch | PR | Notes |
|---|---|---|---|---|
| TH-05 catalogue prices with date/source, manifest model ids, temperature/seed notes | todo | | | real prices/model access from provider consoles = owner |
| TH-02 Postgres retriever in the experiment, manifest fields | todo | | | DB-backed tests run in CI only |
| TH-01 attempted-hallucination metric, METODYKA note, A-unguarded ablation | todo | | | |
| TH-03 dataset ingestion with double verification | needs owner | | | data collection, licences, verification = owner; code side: SOURCE/verification templates, agreement metric |
| TH-06 extra error classes in validation experiment | todo | | | |
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
| ARCH-01 deployment tiers ADR | todo | | | acceptance = owner |
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
