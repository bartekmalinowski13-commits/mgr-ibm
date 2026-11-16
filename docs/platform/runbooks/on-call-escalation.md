# Runbook: on-call and escalation

Audit finding OPS-06. The project is small, so this is deliberately light. **Names and contact
details are not stored in the repository** (personal data); keep them in the team password manager
under "On-call roster".

## Roles

| Role | Does |
|---|---|
| On-call engineer | acknowledges alarms, runs `incident-response.md` |
| Owner | decisions: customer communication, breach notification, spending, restore; escalation point |
| Provider support | Supabase / Fly / AWS tickets, opened by the on-call engineer |

## Rota

One person on call per week, handover on Monday. While there is a single engineer, that person is on
call and the owner is the escalation point; say so in customer contracts instead of promising 24x7.
Business-hours support is the honest default for the pilot (owner decision, DECISIONS_LOG
2026-11-16 OPS-06).

## Alerting

AWS: `ALARM_EMAIL` receives the CloudWatch alarms. Pilot: there is no pager yet (OPS-01/OPS-02); the
owner configures an uptime check on `/readyz`. Conditions that must page: `/readyz` failing for 5
minutes, a non-empty DLQ (`README.md`, "incident: messages in the DLQ"), database connection errors,
an audit-chain verification failure, 5xx rate above 5% for 10 minutes.

## Escalation ladder

1. The on-call engineer acknowledges within the severity target (`incident-response.md`).
2. No acknowledgement within 15 minutes (Sev 1), or a decision is needed -> owner.
3. Provider problem -> open a ticket and note its id in the incident log.
4. Any suspected personal-data breach -> owner immediately, start `security-incident-breach.md`.

## Handover checklist

Open incidents and their state; pending key rotations (`key-rotation.md`); date of the last restore
drill (`backup-restore-dr.md`); anything deployed but not yet verified.
