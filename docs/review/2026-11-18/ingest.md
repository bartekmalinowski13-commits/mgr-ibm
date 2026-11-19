# Code review: ingest and parsing of untrusted customer files

Reviewed at `origin/main` f704a8f. Scope: `services/ingest-worker`, `services/kb-indexer`, `packages/py/cad-parsers` (all parsers, `sandbox.py`, `_sandbox_child.py`, `registry.py`), `packages/py/kb` (extract/safety), the API upload path that feeds them, and the related queue and infra wiring.
How I checked: I read the code. I ran the ingest, parser and KB suites in a temporary worktree (193 passed). I fed crafted hostile files (PDF, ZIP, XML, KiCad) to the parsers, both in-process and through `parse_files_sandboxed`. The worktree has been removed.

## Strengths

- **Layered parse sandbox.** The child runs under `python -I` with RLIMIT_AS, RLIMIT_CPU, a wall-clock timeout, NOFILE 32, FSIZE 0 and `no_new_privs`, and gets a minimal environment. The parent is non-dumpable. Every failure maps to a `ParseError` code, so a bad file never redelivers forever. A 1.5 MB ZIP bomb and a 5M-component KiCad fan-out both ended cleanly as `parse.resource_limit` in about 1 s and 13 s.
- **Bounded before loading.** `ProjectSize` is checked from the size stored in the DB before any object is downloaded. That size is measured on the server (`measure_upload`), not claimed by the client, and the API enforces the same limits.
- **Tenant scoping of objects is enforced twice.** The handler checks `key_belongs_to` on every row, and `S3ObjectStore._check` checks again against the active tenant scope. The ingest task role is read-only on files (`grantFiles(task, false)`). Malware scanning happens before any parser touches the bytes and fails closed. The rejection message is generic and audited.
- **XML handling is correct.** defusedxml is used with `forbid_dtd=True`. I verified that XXE and billion-laughs are refused (`xml.forbidden`), UTF-16 parses, and XInclude and 100k-deep nesting are inert.
- **Archives are read in memory only and paths are checked.** `_safe` rejects absolute paths, `..` and drive letters, and links are refused. Gzip decompression is bounded and multi-member streams are handled. The S-expression reader is iterative and has depth and token caps.
- **The registry contains parser errors.** It turns any parser exception into `parse.internal`, and `pdf_bom` catches the full pypdf error set, including RecursionError.

## Issues

### Critical

None verified.

### Important

**I1. A file uploaded or replaced during an ingest is marked `parsed` without being scanned or parsed. A run can then use its unscanned bytes.**
- **Where:** `services/ingest-worker/src/bomagent_ingest/handler.py:89-97` (SELECT in transaction 1) and `:132-139` (`UPDATE projects.files SET status = ... WHERE project_id = :p` in transaction 2).
- **What is wrong:**
  - `upsert_file` (`services/api/.../repositories/projects.py:239`) resets a replaced row to `uploaded` with a new `object_key`.
  - If that happens between the worker's SELECT and its UPDATE, the UPDATE marks the new row `parsed` and attaches the old file's summary.
  - `parsed_object_keys` (repositories/projects.py:100-110) then hands the new, unscanned object key to `create_run`.
  - The agent-worker parses it (`agent-worker/handler.py:353-360`) before the second ingest message is scanned.
  - With up to 4 ingest tasks (`compute-stack.ts`, `maxTasks: 4`), the stale UPDATE can also land after the newer message finished. The wrong summary then stays permanently.
- **Why it matters:** It defeats the "scan before any parser" guarantee (SEC-09), and the agent-worker that would parse the bytes has internet egress. The UI can also show a summary of a file that no longer exists.
- **Fix:**
  - Update only the rows that were actually loaded: `... WHERE project_id = :p AND id = ANY(:ids) AND object_key = ANY(:keys)`. A per-row `(id, object_key)` compare-and-set is better still.
  - Do the same for the audit `files` count.
  - Add an integration test that replaces a file between the load and the write-back.
- **Owner-reserved:** no.

**I2. The KiCad component budget can be bypassed through sheet fan-out (input of about 0.5 MB gives millions of components).**
- **Where:**
  - `packages/py/cad-parsers/src/bomagent_cad/kicad.py:230` checks only `len(ctx.components)`, and only on entry to a sheet.
  - `:312` appends to `ctx.duplicates`, which is never bounded.
  - `sandbox.py:189-207` has no cap on the size of the design that comes back.
- **What is wrong:** Take a root with N `(sheet ...)` entries that all point to one child sheet whose symbols have no instance data. Every repeated instance pushes each symbol into `duplicates`.
- **Measured:**
  - Root 7 KB + child 463 KB, 80 instances, through the production sandbox: succeeded with **400,000 components** (4x `MAX_COMPONENTS`). The parent's RSS reached 745 MiB, and the parent process has no memory limit.
  - 999 instances: 4,995,000 components, 6.5 GB RSS and 81 s in-process (the CLI and tools call `parse_files` directly). In the sandbox this case is contained as `parse.resource_limit`.
- **Why it matters:**
  - The parser-level budget, which is the documented first line of defence, does not hold.
  - A design that passes reaches the agent run with hundreds of thousands of items, which is LLM cost abuse (per SECURITY.md).
  - The unbounded parent process (2 GiB task) has to absorb `json.loads` and `model_validate` of a reply up to 128 MiB.
- **Fix:**
  - Count `len(ctx.components) + len(ctx.duplicates)` against `MAX_COMPONENTS`, and check it inside `_add_symbol`, not only per sheet.
  - Optionally stop adding a symbol to `duplicates` when its UUID was already seen.
  - Add a global guard in `registry.parse_files` (`len(design.components) > MAX_COMPONENTS` gives `file.too_large`).
  - Lower `MAX_REPLY_BYTES` to something proportional, for example 32 MiB.
  - Add this input to `test_hostile_inputs.py`.
- **Owner-reserved:** no.

**I3. The ODB++ ZIP decompression limit trusts the declared sizes. A 1.5 MB ZIP decompresses to the memory limit.**
- **Where:** `packages/py/cad-parsers/src/bomagent_cad/odbpp.py:152` sums `info.file_size` from the central directory, which the attacker controls. `:165` calls `archive.read(info)`.
- **What is wrong:** CPython's `ZipExtFile.read()` makes a single `decompress(data, MAX_N)` call and only afterwards truncates to the declared size. A member that declares 1000 bytes but holds 1.5 GiB of deflated zeros therefore allocates the whole output.
- **Measured:** In-process under a 1 GiB RLIMIT_AS, `MemoryError` after 0.7 s at 846 MiB RSS. Through the sandbox, `parse.resource_limit` ("memory limit exceeded") instead of `archive.too_large`.
- **The test misses it:** `test_odbpp.py:102` only uses honest headers.
- **Why it matters:** The docstring and FORMATS.md promise that "a decompression bomb stops early" at parser level. For ZIP it does not; only the sandbox's RLIMIT stops it, and in-process callers (CLI, `tools/`) are unprotected. The user also gets the wrong error code.
- **Fix:**
  - Read each wanted member in a bounded loop: `with archive.open(info) as h:` then read 64 KiB chunks, counting the real bytes against a shared `MAX_TOTAL_BYTES` budget, and raise `archive.too_large` when it is exceeded.
  - Optionally reject a `compress_size / file_size` ratio above about 1000.
  - Add a test with a patched `file_size`.
- **Owner-reserved:** no.

**I4. KB-document parsing (pypdf / Docling) runs in-process in kb-indexer, without the sandbox and on the event loop. Errors pypdf raises on hostile input escape as transient failures.**
- **Where:**
  - `services/kb-indexer/src/bomagent_kb_indexer/handler.py:67-76` and `:88` call the synchronous `extract()` inside `async def`.
  - `packages/py/kb/src/bomagent_kb/extract.py:58-70` catches only `(PdfReadError, ValueError, KeyError, TypeError)`.
  - `docling_extract.py` catches nothing.
- **Measured with crafted PDFs:**
  - Content stream with 200k nested `[`: `RecursionError` escapes.
  - FlateDecode stream that inflates to 1 GiB: `pypdf.errors.LimitReachedError` (a PyPdfError, not a PdfReadError) escapes.
  - Both propagate out of `_tenant`. The message is retried 5 times and then dead-lettered.
- **What is wrong:**
  - The document stays `pending` permanently (there is no reaper).
  - The process has no RLIMIT_AS, CPU limit or timeout.
  - The kb-indexer runs in `PRIVATE_WITH_EGRESS` with the LLM gateway key and both DB roles, including the platform role used for the global corpus (`compute-stack.ts:453-461`).
  - A slow or huge PDF blocks the event loop, including `/healthz`, for the whole parse.
  - KB uploads are also not malware-scanned.
- **Why it matters:** SECURITY.md requires "parser in an isolated task without network ... size/time limits" for malicious files, and CLAUDE.md rule 5 says parsers run in isolation. Datasheets are customer files just like design files.
- **Fix:**
  - Short term: broaden the caught set to `pypdf.errors.PyPdfError` and the same tuple that `pdf_bom._pages` uses (RecursionError, AttributeError, IndexError, ...).
  - Wrap Docling as well and map its failures to `ExtractionError`.
  - Run `extract` in `asyncio.to_thread`.
  - Proper fix: run extraction through the same resource-limited child as `bomagent_cad.sandbox`, for example a generic `run_sandboxed(module, payload)`, and scan KB uploads with the same `FileScanner`.
- **Owner-reserved:** no for the code. Moving kb-indexer or its extraction to an isolated subnet is an `infra/cdk` change, which the infra owner should review.

**I5. Files (and KB documents) whose ingest message dead-letters stay `uploaded` / `pending` permanently, with no audit event or user feedback.**
- **Where:**
  - `services/ingest-worker/src/bomagent_ingest/handler.py:63-66` re-raises `ScannerError`, and `:101-103` raises `ValueError`.
  - `bomagent_common/messaging.py:383-389`: a failure is not acked, and the message dead-letters after 5 receives.
  - `services/api/src/bomagent_api/maintenance.py:38-70` reaps only `runs.runs`.
- **What is wrong:**
  - A deterministic clamd error is treated as transient. The README itself names "file exceeds clamd's `StreamMaxLength`" (default 25 MB, while uploads may be 64 MiB). After 5 attempts the project's files remain `uploaded`, with no audit event and no message in the UI.
  - The same happens to the KB documents in I4.
  - The runs reaper exists precisely for this situation, but files are not covered.
- **Why it matters:**
  - The upload is silently stuck, and the only remedy is to re-upload.
  - It contradicts the DoD rule "audit event for data-changing operations".
  - It contradicts the sandbox docstring's promise that a failure "marks the file failed instead of ... redelivering the message forever".
- **Fix:**
  - Classify clamd replies containing `size limit exceeded` (and similar) as permanent: mark the files `failed` with `file.scan_failed` and audit it.
  - Add a maintenance sweep: files `uploaded` older than (ingest visibility × max receives + grace) become `failed` / `ingest.timeout` with an audit event. Do the same for `kb.documents` `pending`.
  - Treat a key outside the tenant prefix as a rejected message (ack and log/audit) rather than retrying it 5 times.
- **Owner-reserved:** no. This touches `maintenance.py` and the handlers, not migrations, unless a new status value needs a CHECK constraint.

### Minor

**M1. The ingest visibility timeout can be shorter than the worst-case handling time.**
- `data-stack.ts:202` sets ingest visibility to 10 min.
- The handler scans up to 50 files one after another, with a 30 s clamd timeout each (`scanner.py:33`), and then parses for up to 90 s. The worst case is about 26.5 min.
- With a slow clamd, the message reappears and a second worker processes the same project at the same time, which makes I1 worse.
- **Fix:** scan with bounded concurrency and an overall deadline below the visibility timeout (for example a 480 s total budget), or extend visibility while working.
- **Owner-reserved:** no (`infra/cdk` only if the timeout is changed instead).

**M2. Malware-rejected projects record no parse outcome metric.**
- `handler.py:123-127` skips `metrics.record_parse(...)` for `MalwareDetectedError`, so dashboards of parse outcomes undercount failed projects.
- **Fix:** call `record_parse("failed", MALWARE_ERROR, ...)`.
- **Owner-reserved:** no.

**M3. The IPC-2581 docstring claims the document is "size-limited by `FileRef`", but `FileRef.__init__` has no limit.**
- `ipc2581.py:3-4`. Only `FileRef.from_path` checks `MAX_FILE_BYTES` (`base.py:42-47`). In the services the 64 MiB API limit and `ProjectSize` provide the bound, so this is a documentation/defence-in-depth gap, not an exploit.
- **Fix:** check `len(file.data) > MAX_FILE_BYTES` in `parse_files` (registry) as well, and correct the docstring.
- **Owner-reserved:** no.

## Declined to judge

- **Malware scanning in production.** The scanner is the EICAR stub unless `BOMAGENT_MALWARE_SCAN_CLAMD_ADDR` is set, and nothing in the repo deploys clamd or GuardDuty S3 scanning. This is already tracked as an owner/deploy action (PROGRESS SEC-09, DECISIONS_LOG M9), so it is not counted.
- **Network isolation of the parse child on Fargate/Fly.** `unshare(CLONE_NEWNET)` needs CAP_SYS_ADMIN, so the child keeps the task's network: VPC endpoints and Postgres for ingest; internet and the LLM gateway for the agent-worker and the all-in-one pilot. A hijacked child can also signal (kill) its same-UID parent. This is known and tracked as SEC-01 / ARCH-02 (owner, deploy/*). I did not evaluate exploitability beyond that.
- **Exploitability of native code paths.** I did not fuzz ezdxf `recover`, pypdf or Docling for exploitable crashes, only for error handling and limits.
- **Agent-side handling of prompt injection from parsed content.** Outside this area.
