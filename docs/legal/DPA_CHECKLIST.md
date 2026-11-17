# DPA checklist (data processing agreements)

Status: **checklist, not legal advice.** It lists what to collect and verify for each vendor before
the platform processes real customer data. Every box is open until the owner confirms it; nothing
has been verified with a vendor. Related: `SUBPROCESSORS.md`, `docs/platform/SECURITY.md`,
`docs/platform/runbooks/tenant-offboarding.md`.

## A. Our own DPA with customers (BOM Agent as processor)

- [ ] Template exists and has been reviewed by a lawyer (Art. 28 GDPR: subject matter, duration, nature and purpose, data categories, data subjects).
- [ ] Documented instructions: process only on the customer's instructions.
- [ ] Confidentiality of persons authorised to process.
- [ ] Security measures annexed (reference `SECURITY.md`; tenant isolation, EU only, audit log).
- [ ] Sub-processor clause: list (`SUBPROCESSORS.md`), notification period, right to object.
- [ ] Assistance with data-subject requests: export is available (`POST /v1/organizations/{id}/export`); organisation deletion is an open owner decision (see the offboarding runbook).
- [ ] Breach notification period agreed (see `runbooks/security-incident-breach.md`).
- [ ] Return or deletion at the end of the contract, including backup expiry wording (do not promise immediate erasure from all copies until decided).
- [ ] Audit and inspection rights.
- [ ] International transfers: the EU-only statement matches what is deployed.

## B. For each vendor (Supabase, Fly.io, AWS, every enabled LLM provider, e-mail relay, observability)

- [ ] Signed or accepted DPA on file (date, version, signatory).
- [ ] Processing region confirmed in writing and equal to what is configured (project region, app region, bucket region, model region or profile).
- [ ] Vendor's own sub-processor list reviewed; change-notification mechanism subscribed to.
- [ ] Transfer mechanism for any non-EU access (SCCs or an adequacy decision), including support access from outside the EU.
- [ ] Retention of logs, backups and prompts/responses known; zero-retention or opt-out of abuse monitoring requested where offered.
- [ ] No training on customer data (contractual, not only a setting).
- [ ] Encryption at rest and in transit confirmed; who holds the keys.
- [ ] Breach-notification obligation and contact.
- [ ] Deletion at termination and how long backups persist.
- [ ] Certifications noted (for example ISO 27001, SOC 2) with report dates.

## C. Vendor-specific points

- **Supabase**: the Data API must not expose our schemas (ADR-0017); region of the project and of backups; where Auth user data lives.
- **Fly.io**: whether persistent volumes or logs can hold customer data; region pinned to `fra`.
- **AWS**: account structure and SCP region guard (ADR-0002); KMS keys; accepting the DPA in the console is an owner action.
- **LLM providers**: model-level regional availability changes, so re-check at every model enablement (ADR-0006); data-zone or EU-profile setting; abuse-monitoring retention.

## D. Records to keep

- [ ] Register of processing activities (Art. 30) entry for BOM Agent as processor.
- [ ] DPIA decision recorded (needed or not, with reasoning).
- [ ] Date of the last review of this checklist and of `SUBPROCESSORS.md`.
