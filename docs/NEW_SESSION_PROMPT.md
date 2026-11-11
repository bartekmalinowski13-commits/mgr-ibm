# Prompt for a new session (copy everything below the line)

---

You are continuing work on the **BOM Agent** project (master's thesis + production B2B SaaS).

**Repository:** https://github.com/bartekmalinowski13-commits/mgr-ibm
**Working branch:** `claude/code-master-prompt-part-2-5651f9` (all work so far is here; not merged to `main`, PR not opened yet — do not open it until I ask). Work and push only to this branch.

## Start by reading (in this order)

1. `docs/HANDOFF.md` — **where I stopped, what remains to be done (in order), what is waiting on me, environment notes**. This is the main document.
2. `CLAUDE.md` — inviolable rules (tenant isolation, EU only, no learning across organizations, secrets, customer files as untrusted, **no deployments to AWS from a session**, no real LLM keys in tests, no force-push to `main`).
3. `docs/STATUS.md` — the state of each milestone (M0–M8).
4. `docs/DECISIONS_LOG.md` — assumptions made without consultation; rows with "yes" in the last column are waiting for my acceptance.
5. If needed: `docs/platform/ARCHITECTURE.md` (source of truth), `docs/adr/`, `docs/platform/SECURITY.md`, `docs/platform/TESTING.md`, `docs/platform/FORMATS.md`, `docs/plans/` (plans M1–M7 and SSO), `docs/platform/runbooks/README.md`.

## Task

Carry out the open tasks from `docs/HANDOFF.md`, section "Next tasks for Claude Code", **in the given order**:

1. check CI for the latest commit (SSO) and fix whatever is red;
2. repeat the **SSO security review** (it was interrupted, no results) and fix all CRITICAL/HIGH findings;
3. deferred review remarks (list in `DECISIONS_LOG.md`);
4. LangGraph checkpoints in Postgres with RLS, KB budget/snapshot in the Agent SDK adapter;
5. prepare the list of assumptions for my acceptance;
6. **at the end**: translate the remaining Polish documents into English (except `docs/thesis/`).

Process for each task: TDD → implementation → subagent review → verification (`just lint`, tests, `just openapi` after API changes) → update `docs/STATUS.md` → commit and push to the working branch. Write new documentation **in English only**. Commits: Conventional Commits, in English.

## What not to do

- Do not deploy to AWS and do not create cloud resources.
- Do not commit secrets or `.env`.
- Do not silently decide on items from the "waiting on the owner" list (experiment data, access to EU models, AWS account/domain) — describe them in the final report.

## At the end

Update `docs/STATUS.md` and `docs/HANDOFF.md`, and in your reply state: what is done, what is waiting on me, which assumptions need my acceptance, and what % of the task is complete.
