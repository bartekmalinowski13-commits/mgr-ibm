# Runbook: security incident and personal-data breach (GDPR Art. 33/34)

Audit finding OPS-06. This is an engineering checklist, **not legal advice**; the owner takes the
notification decisions, ideally with counsel or the DPO. Pair with `incident-response.md`.

## Roles

- **Incident lead** (the on-call engineer, `on-call-escalation.md`): runs containment and the log.
- **Owner**: decides on notifications. For customers' design data the **customer is the controller
  and we are the processor**; for account data (users, e-mails) we are the controller. Check the DPA
  for the customer deadline: a processor must notify the controller **without undue delay** (many
  DPAs say 24-48 h), shorter than the 72 h the controller then has towards the authority.

## The clock

GDPR Art. 33: the **controller** notifies the supervisory authority **within 72 hours of becoming
aware** of a personal-data breach, unless it is unlikely to result in a risk to people. Write the
exact time of awareness on the first line of the incident note; the clock runs on calendar hours,
weekends included. A late notice must state the reason. Art. 34: if the risk is high, affected people
are informed without undue delay.

## Steps

1. **Contain (first hour)**: revoke/rotate exposed credentials (`key-rotation.md`), disable the exploited path, isolate the affected tenant or service. Do not wipe anything: preserve logs, the database state and the audit chain (take a dump first, see `backup-restore-dr.md`).
2. **Scope**: which tenants, which data (design files, BOMs, user e-mails, tokens), how many people, since when, still ongoing? Use `audit.events` (`source_ip`, actor, action), access logs, Fly/CloudWatch/Supabase logs, bucket access logs. Verify the audit chain for the affected tenants (`audit.verify_chain`, and against the anchors); a broken chain is itself a finding.
3. **Assess risk** (owner): confidentiality, integrity or availability; type and sensitivity (design files can be trade secrets); how easily people are identified; whether the data was encrypted. Check uploads for patient data.
4. **Notify the customer(s) as controller - target within 24 h of awareness, sooner if the DPA says so**: what happened, when found, data and tenants affected, likely consequences, measures taken, a contact. Send in stages if facts are incomplete and say so.
5. **Supervisory authority**: the controller, or we for our own account data, within 72 h of awareness (Poland: UODO breach form; otherwise the authority of the controller's establishment). Content: nature, categories and approximate numbers, contact point, likely consequences, measures. Phased reports are allowed.
6. **Data subjects** (Art. 34) when the risk is high: plain language, what happened, what to do, a contact. The controller decides and sends.
7. **Record** every breach, notified or not, with the reasoning (Art. 33(5)): date, facts, effects, actions. Keep it in the private incident log.
8. **Recover** (`backup-restore-dr.md`), then a post-mortem; fixes go into `docs/platform/SECURITY.md` through a `docs(spec)` change and, where a decision changes, an ADR.

## Evidence handling

Keep copies of logs outside the compromised system, read-only. Do not put customer data in tickets.
Give the customer an audit extract for their own tenant only, never another tenant's data.

## Owner to fill in (not known to the repository)

Legal entity and DPO/contact details, the supervisory authority, notification contacts per tenant,
counsel contact. Until then this runbook cannot be completed end to end.
