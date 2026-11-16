# Runbook: incident response (operations)

Audit finding OPS-06. For personal-data incidents also follow `security-incident-breach.md`. All
cloud actions are done by a **human** (CLAUDE.md rule 6).

## Severity

| Sev | Meaning | Examples | Response target |
|---|---|---|---|
| 1 | Production down, data loss, cross-tenant exposure, active attacker | RLS bypass, leaked key in use, database gone | start within 30 min, best effort 24x7 |
| 2 | Major feature broken or degraded for many tenants | runs failing, uploads failing, `/readyz` red | start within 2 h on working days |
| 3 | Minor, workaround exists | one tenant affected, cosmetic | next working day |

The targets are proposals; the owner confirms them (DECISIONS_LOG 2026-11-16, OPS-06).

## Procedure

1. **Detect and acknowledge**: alarm, customer report or own observation. Open a private incident note (time-stamped log; no customer data or secrets in it).
2. **Classify** severity. Any suspicion of unauthorised access to or loss of customer data = **Sev 1; start `security-incident-breach.md` in parallel** (its 72 h clock starts at awareness).
3. **Contain** before fixing: disable the affected feature or tenant, revoke/rotate the leaked credential (`key-rotation.md`), stop a bad rollout.
4. **Diagnose**: `/healthz`, `/readyz`; `fly logs -a <app>` or CloudWatch `/bomagent/<env>/<worker>`; OTel traces; the audit log (`audit.events`) for who did what; recent deploys (`fly releases`).
5. **Fix or roll back**: prefer rolling back to the previous release over a hot fix; a data problem goes to `backup-restore-dr.md`. Messages stuck in a queue: "incident: messages in the DLQ" in `README.md`.
6. **Verify**: smoke tests (`just smoke`), watch the error rate for 30 minutes.
7. **Communicate**: Sev 1/2 - tell affected customers what happened, the impact and when the next update comes; update every 60 minutes (Sev 1) until resolved. Do not speculate about the cause.
8. **Close and learn**: blameless post-mortem within 5 working days: timeline, root cause, what detected it, what slowed us down, action items with owners. A changed decision becomes an ADR; update the affected runbook.

## Do not

- Do not run commands against production from a Claude Code session; use it only to analyse exported logs.
- Do not delete audit rows or anchors, even if they look wrong.
- Do not paste secrets or customer file contents into chats, tickets or the incident note.
