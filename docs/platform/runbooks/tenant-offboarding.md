# Runbook: tenant offboarding (export and deletion)

Audit finding OPS-06. `SECURITY.md`: export and permanent deletion of an organization's data, with
confirmation in the audit log. Never delete tenant data by hand with an admin role; RLS and the audit
chain are what keep other tenants safe.

## Preconditions

- Written request from an **owner** of the organization (not any member) or a contract termination; record who and when.
- Confirm identity out of band (reply from the contract e-mail, not only the app).
- Check for a legal hold or an open incident involving the tenant.

## Steps

1. **Freeze**: make the tenant read-only / disable sign-in for non-owners (support action, audit event).
2. **Export**: give the customer their data (BOMs with versions, source files, audit extract for their tenant) using the application export, not a raw dump; check the file list against the tenant's row counts. Deliver by an expiring link, not an e-mail attachment.
3. **Confirm in writing** that they received the export and want deletion; keep the confirmation.
4. **Cooling-off**: wait the contractual period (suggested 30 days; owner decision, DECISIONS_LOG 2026-11-16 OPS-06) before irreversible deletion.
5. **Delete** through the application's organization deletion (runs in the tenant context, writes the confirming audit event). It must remove: database rows of every tenant-scoped table, files under the tenant's Storage/S3 prefix, knowledge-base vectors, caches and agent memory of that tenant (CLAUDE.md rule 3), the SSO connection, and Auth users that belong to no other organization.
6. **Verify**: zero rows for the tenant id in every tenant table; the bucket prefix is empty; the cross-tenant isolation test still passes (`just test`).
7. **Backups**: deleted data stays in backups until they expire (lifecycle in `backup-restore-dr.md`). Tell the customer that period. After any restore, **re-run the deletion** for every tenant deleted since the backup date; keep a list of deleted tenant ids and dates.
8. **Audit anchors** are immutable and hold only a hash and a sequence number, no customer data; keep them (DECISIONS_LOG, SEC-04). A purged chain reads as tamper until the retire mechanism exists - record the tenant id as intentionally purged.
9. **Confirm** the deletion to the customer in writing with the date and the backup expiry date.

## Open points for the owner

Cooling-off length, backup retention versus erasure promises, and whether audit rows of a deleted
tenant are purged or kept anonymised (the IP-address question in DECISIONS_LOG, SEC-04). Until
decided, do not promise "immediate erasure from all copies".
