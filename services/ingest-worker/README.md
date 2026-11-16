# ingest-worker

Consumes `file.uploaded` from the `ingest` queue: loads the file from the tenant prefix,
parses it in the resource-limited sandbox (`bomagent_cad.sandbox`) and stores the parse
summary on `projects.files` in the message's tenant context (RLS).

Config: `BOMAGENT_DATABASE_URL`, `BOMAGENT_QUEUE_URL`, `BOMAGENT_FILES_BUCKET`.
Health: `/healthz`, `/readyz`.

**Queue backend:** `BOMAGENT_QUEUE_BACKEND=sqs` (default, AWS: `BOMAGENT_QUEUE_URL`) or
`postgres` (Supabase pilot: `app.queue_messages`, queue `BOMAGENT_QUEUE_NAME`, default
`ingest`; consumed with the platform role, so `BOMAGENT_PLATFORM_DATABASE_URL` or
`BOMAGENT_PLATFORM_DATABASE_PASSWORD` is required). Without either the worker runs in
health-only mode.

Tests: `uv run pytest services/ingest-worker tests/services` (PostgreSQL).

## Malware scan (audit SEC-09)

Every file is scanned **before any parser runs** (`bomagent_ingest.scanner`, `FileScanner`
protocol). If any file in a project is flagged, the whole project is marked `failed` with the
generic error `file.rejected` (no signature, scanner or file name shown to the user), an audit
event `project.file_malware_detected` records the file names and signatures, and
`bomagent_malware_scan_total{outcome=clean|infected|error}` plus
`bomagent_malware_scan_duration_s` are emitted.

- Default: `EicarScanner` - always on, only rejects the EICAR test string (proves the wiring).
- ClamAV: set `BOMAGENT_MALWARE_SCAN_CLAMD_ADDR` to `tcp://host[:3310]` or
  `unix:///path/to/clamd.sock` (optional `BOMAGENT_MALWARE_SCAN_TIMEOUT_S`, default 30).
  Unset = off. Running clamd is a deployment concern; this repository does not ship it.
- Fail closed: if clamd is unreachable, times out or errors (e.g. the file exceeds clamd's
  `StreamMaxLength`), nothing is parsed and the queue message is retried / dead-lettered.
- Tests: `services/ingest-worker/tests/test_scanner.py` (EICAR + fake clamd, no database) and
  `test_ingest_malware.py` (PostgreSQL, `integration`).
