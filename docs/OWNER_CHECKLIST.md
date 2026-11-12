# Owner checklist - from the repository to a running app

## Status 2026-11-13 (live pilot) - what is next

**Live:** https://mgr-ibm-bomagent.fly.dev (Fly.io `fra` + Supabase `eu-west-1`, project MGR-IBM). `main` = deployed (Fly release v4). Runs still use the **fake model** (`/readyz` shows `"llm":"fake"`). Every new organisation gets 5 `[Sample]` projects automatically; existing organisations use the "Add sample projects" button (see `docs/owner-guides/PRZYKLADOWE_DANE.md`).

Your remaining clicks, in the order that unblocks the most:

1. **Google sign-in (about 5 min).** Everything except the secret is prepared (`docs/platform/runbooks/social-login.md`, section "Prepared in consoles"): Google Cloud -> project `mgr-ibm` -> Google Auth Platform -> Clients -> "MGR-IBM Supabase" -> **Add secret** -> copy -> Supabase -> Authentication -> Sign In / Providers -> Google -> paste Client ID + secret -> Save. Then tell Claude Code: it sets `BOMAGENT_SOCIAL_PROVIDERS` and redeploys. The app is in Testing mode: add every person who should sign in with Google (e.g. the supervisor) under Audience -> Test users.
2. **Microsoft sign-in is blocked** until you have an Entra directory (sign up for an Azure free account - card + phone verification - or the Microsoft 365 developer programme). Then the steps under "once a directory exists" in the same runbook.
3. **LLM keys** (`docs/owner-guides/KLUCZE_LLM_KROK_PO_KROKU.md`, Polish, step by step): Mistral first (fastest), then AWS Bedrock (Claude, Qwen) and Azure OpenAI. Run `tools/pilot-llm-setup.sh` in a terminal: it asks each key silently and stages the gateway secrets on Fly. Then tell Claude Code which providers you set: it enables the verified models in the catalogue (PR), deploys the gateway and switches the pilot over (`docs/platform/runbooks/llm-gateway-pilot.md`, steps 8-12).
4. **Local models** (Ollama on your Mac, for learning and experiments): `docs/platform/runbooks/local-models.md`.
5. **Before sending the link to the supervisor:** sign up yourself once in the app (confirm the e-mail), walk through a sample project (upload, run, BOM, correction, export), upgrade the Supabase project from the Free plan (idle projects are paused) and accept ADR-0017 / the rows marked "yes" in `docs/DECISIONS_LOG.md`. Real BOMs for the thesis need step 3.
6. **AWS path** (optional, "proper" production-like deployment): `docs/platform/runbooks/single-account-dev.md` (about 1-2 h of your clicks + first pipeline run).


Status as of 2026-11-12. Everything that can be done without you is done and pushed to
`claude/code-master-prompt-part-2-5651f9` (CI green). What remains needs your accounts,
your decisions or your data. Claude Code never creates cloud resources (CLAUDE.md §6).

## What is ready

| Area | State |
|---|---|
| Application (web + API + workers, M0-M5, M7) | done, tested (Python, TS, E2E + accessibility) |
| Local demo on your Mac | done: `just demo` -> http://localhost:5173 (`HANDOFF.md`, "Local demo") |
| AWS infrastructure as code (M6) | done, never deployed; single-account dev path added |
| Supabase pilot variant (ADR-0017, proposed) | done, tested locally; never deployed |
| Experiment tool for the thesis (M8) | done; needs your data and EU model access |
| First real deployment | **not yet** - expect a few fixes from the first deploy logs |

## Steps (in this order)

### A. Today, 10 minutes - see it working

1. Run the local demo on your Mac (`HANDOFF.md`, "Local demo"). Click through: project,
   run A and B, BOM, correction, export, compare, audit log, settings.

### B. Review and merge

2. Open a PR from `claude/code-master-prompt-part-2-5651f9` to `main`, review, squash merge.
3. Branch protection on `main`: require the `tenant isolation (blocking)` check.
4. Decide on the assumptions awaiting acceptance (`HANDOFF.md`, "Assumptions awaiting your
   acceptance"; `DECISIONS_LOG.md` rows with "yes"), in particular **ADR-0017** (Supabase
   variant) before using it with anything but test data.

### C. Quick pilot for testers (optional, about 1-2 hours) - Supabase + Fly.io

5. Follow `docs/platform/runbooks/supabase-pilot.md`: Supabase project in Frankfurt (Confirm
   email ON, asymmetric JWT keys, private bucket, S3 key), database preparation from your Mac,
   Fly app + secrets, `fly deploy`, first sign-in.
6. Runs use the fake model there unless you add an EU LLM gateway - fine for testing the
   product flow, not for real BOMs.

### D. Primary path - AWS, one account, dev (about 1-2 hours + first pipeline run)

7. Follow `docs/platform/runbooks/single-account-dev.md`: account + MFA + IAM Identity
   Center, CDK bootstrap, Cicd stack with the **monthly budget**, Bedrock model access,
   GitHub environments and variables, merge -> pipeline -> app URL.
8. Tell Claude Code which Bedrock models are enabled - it enables them in the model
   catalogue (one commit). Then runs produce real BOMs.

### E. Thesis experiment (M8)

9. Collect at least **6** open biomedical KiCad designs with licences and hand-checked
   reference BOMs (`evals/fixtures/kicad/<design>/reference_bom.csv`; candidates in
   `docs/thesis/ZBIOR_EWALUACYJNY_KANDYDACI.md`). With 3 designs the smallest attainable
   p-value is 0.25, with 6 it is 0.031.
10. With EU models enabled: `uv run bomagent experiment run evals/experiments/<real>.yaml`
    (figures and tables for chapter 7 are generated by the same command).

### F. Before real customers

11. Multi-account AWS layout with SCPs, staging, prod with a domain and certificates
    (`docs/platform/runbooks/README.md`), SES for e-mail, the remaining deferred review items
    (`HANDOFF.md`, "Still open").

## When something fails

Copy the exact error (GitHub Actions log, `fly logs`, terminal output) into a Claude Code
session on this repository - fixes go through code and the pipeline, never by hand in the
cloud console.
