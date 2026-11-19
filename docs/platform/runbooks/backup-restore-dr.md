# Runbook: backups, restore and disaster recovery

Audit finding OPS-05. All steps are done by a **human** (CLAUDE.md rule 6). `<...>` = placeholder.
Related: `supabase-pilot.md`, `key-rotation.md`, `incident-response.md`.

## 1. Recovery objectives

| Tier | What | RPO (max data loss) | RTO (max time to restore service) |
|---|---|---|---|
| Pilot (Supabase + Fly, ADR-0017) | Postgres, Supabase Storage | 24 h without PITR; **<= 15 min with PITR** (paid plan, required once real users are on it) | 8 h |
| AWS target (ADR-0002) | Aurora, S3 | <= 5 min (Aurora continuous backup / PITR) | 4 h |

These numbers are **targets proposed by the engineers** (DECISIONS_LOG, 2026-11-16 OPS-05); the owner
must accept or change them before they go into a customer contract or DPA. Free Supabase projects
have no PITR and are paused when idle: the pilot is not a production tier until it is on a paid plan
with PITR enabled.

## 2. What is backed up, and where

| Data | Pilot | AWS target |
|---|---|---|
| Postgres (all tenants, audit chain, queues) | Supabase PITR (WAL) + daily managed backup; **plus** a nightly `pg_dump -Fc` to an EU bucket (below) | Aurora automated backups + PITR; AWS Backup copy to `eu-west-1` |
| Files (uploads, exports) | Supabase Storage is **not** covered by database backups: nightly sync of the bucket to the EU backup bucket | S3 versioning + AWS Backup / replication to `eu-west-1` |
| Audit anchors (`audit-anchors/<tenant>/<date>.json`) | their own write-once bucket + off-platform copy (SEC-04) - **not** restored from backup | same |
| Secrets | password manager + `fly secrets` / Secrets Manager; in no dump | same |
| Configuration | git (`main`) | git |

EU only (CLAUDE.md rule 2): backup buckets and the drill database must be in the EU. Backups hold
customer data, so the backup bucket needs the same protection as production (separate key,
encryption at rest, no public access) and a lifecycle rule (suggested 35 days; the owner decides and
records it together with the retention for deleted tenants, see `tenant-offboarding.md`).

### Nightly dump (pilot) - the owner sets up the schedule

```bash
# operator machine or a scheduled CI job in a protected environment; the URL is a secret
pg_dump "$BOMAGENT_BACKUP_DATABASE_URL" -Fc --no-owner -f "bomagent-$(date -u +%F).dump"
# upload to the EU backup bucket with a key that can write but not delete
```

Use the `postgres` admin or a read-only role that can read every schema and table (the RLS-bound
application roles would dump nothing). The dump only reads production.

## 3. Restore drill (monthly, and after any change to backups or audit anchors)

`tools/restore_drill.py` restores a dump into a **new scratch database** and verifies it. It refuses
any database whose name does not start with `restore_drill_`, refuses a name that already exists,
needs the name repeated in `--confirm-scratch`, and never modifies the dump or an existing database.

```bash
export BOMAGENT_DRILL_ADMIN_URL='postgresql://<admin>@<scratch-server>:5432/postgres'  # NOT production
python tools/restore_drill.py --dump bomagent-<date>.dump \
  --scratch-db restore_drill_<yyyymmdd> --confirm-scratch restore_drill_<yyyymmdd> --dry-run
# then the same command without --dry-run (add --cleanup to drop the scratch database afterwards)
```

Point it at a **separate** scratch server or a throwaway Supabase project, never the production
server (the script cannot tell them apart, so this is on the operator). It prints row counts of
`tenancy.tenants` and `audit.events` and runs `audit.verify_chain` for every tenant; exit 0 only when
every chain verifies. Compare the counts with production, allowing for the dump's age. Record each
drill (date, dump age, duration, result) in the ops log; the duration is the measured RTO.

Not covered by the script: restoring Storage objects, and checking the chain **against the anchors**
(`verify_chain(anchors=...)` needs the sink credentials). Do both by hand on the first drill.

## 4. Restore procedure (real incident)

1. **Declare** an incident (`incident-response.md`); stop the damage first (rotate a leaked key, block a bad deploy).
2. **Decide the target time**: the last good moment (before the bad migration, delete or attack).
3. **Restore into a NEW database/project**, never over the damaged one: Supabase -> Database -> Backups -> PITR to a new project (or Aurora PITR to a new cluster). Keep the damaged one until the end for forensics.
4. **Verify** the new instance: dump it and run `tools/restore_drill.py`, or at minimum check row counts and `audit.verify_chain` per tenant.
5. **Audit anchors:** a restore to an earlier time makes a chain shorter than an anchor taken later, which reads as tampering (DECISIONS_LOG, SEC-04 part 2). Before cut-over write down the affected tenants and the restore time and tell the owner; expect verification to flag them until the epoch/retire mechanism exists. Do **not** delete anchors to silence it.
6. **Cut over:** point the app at the new database (`fly secrets`; `bomagent-migrate bootstrap` if roles are missing), run `bomagent-migrate upgrade`, check `/readyz`, run the smoke tests.
7. **Restore files** from the bucket backup if Storage was affected; files uploaded after the backup are lost (RPO) - list the affected tenants.
8. **Re-run deletions** for tenants offboarded since the backup date (`tenant-offboarding.md`).
9. **Notify** customers; if personal data was lost or exposed, follow `security-incident-breach.md`.
10. Post-mortem within 5 working days.

## 5. Scenarios

| Scenario | Action |
|---|---|
| Bad migration / accidental delete | PITR into a new database just before the event (section 4); copy the missing rows back, or cut over |
| Database project lost or paused | restore the latest dump/backup into a new project; re-run `bootstrap` for roles |
| Region outage (Frankfurt) | no automatic failover in the pilot: restore from the EU backup bucket into another EU region within the RTO; AWS target: restore the `eu-west-1` copy |
| Ransomware / credential compromise | `security-incident-breach.md` first; restore only into a clean account/project with new credentials |
| Fly app lost | `fly deploy` from `main`; the app is stateless, secrets come from the password manager |

## 6. Owner-only items (need cloud accounts; not done in the repository)

- Move the Supabase project to a paid plan and enable PITR.
- Create the EU backup bucket, its write-only key and lifecycle rule; schedule the nightly dump and file sync.
- Provide the scratch server for drills; run the first drill and record the measured RTO.
- Accept or change the RPO/RTO above.
- AWS: Aurora backup retention and an AWS Backup plan with the `eu-west-1` copy (CDK change by the owner).
