# Review: agents and the experiment (origin/main f704a8f, worktree /tmp/rev-agents)

Scope: services/agent-worker, packages/py/agents, llm, kb (retrieval and safety), eval, cli (experiment.py, experiment_stats.py, injection), gateway config, #81-#83.
Tests: `pytest packages/py/{agents,eval,llm,cli}` gives 186 passed. Every issue below was checked in the code. The two Critical behaviours were reproduced with probe scripts in `scratchpad/probe/` (p1.py, p4.py).

## Strengths
- The shared "safety floor" is real code. Both variants use the same `choose_mpn`, `guard_mpns`, `Budget`, `guarded` and `finish`. This matches METODYKA §1.
- The prompt-injection boundary is solid. `data_block` escapes every `<`/`>`. KB chunks flagged as suspect are dropped from the excerpts and from the MPN candidates (`candidates_from`), and so from `known_mpns`. The SDK runtime denies the built-in tools explicitly.
- The statistics match the pre-registration. The unit is the design (mean over repetitions). The exact sign-flip test is used up to n=16. Holm is a correct step-down. d_z returns NaN when sd=0. The cluster bootstrap weights each design equally. All of it is seeded.
- The attempted-hallucination metric is NaN, not 0, when there are no decisions or no findings. That matches METODYKA §2.
- Reproducibility: the manifest carries the prompt `version+sha8`, the pinned `gateway_model` (Mistral `-latest` was removed in #83), the KB content hash and the sampling note. The EU guard is fail-closed on the rendered gateway config.
- #83 is reasonable. Timeouts are sized per call, timed-out generations are not retried, and gateway `num_retries: 0` avoids paid duplicate calls.

## Issues

### Critical

**C1. MPN choices are applied a second time, by stale line numbers, in `finish`, so MPNs land on the wrong BOM lines (both variants and production).**
- Where:
  - `packages/py/agents/src/bomagent_agents/variant_b.py:40` and `variant_a.py:147`: `choices: Annotated[list, operator.add]`.
  - `variant_b.py:200` and `variant_a.py:233`: `return {"choices": []}` is meant to clear the list.
  - `variant_b.py:142`: `finish()` calls `apply_choices(state["items"], state["choices"])`.
- What is wrong: with the `operator.add` reducer, returning `[]` appends nothing, so the choices are never cleared. `finish` then re-applies every choice by its *original* `line` number to the *final* items:
  - In B, `assemble` → `renumber` renumbers lines (`bom-core/grouping.py:153` sorts by `natural_key(refdes[0])`).
  - `group_components` (`grouping.py:112`) sorts by `natural_key(min(refdes))`, and `min` is lexicographic. A group {R2, R10} therefore sorts as "R10" in grouping but as "R2" in `renumber`.
  - In A, `compose` renumbers lines 1..n in whatever order the LLM returns them.
- Reproduced:
  - B on components R2+R10 (10k), R3 (1k): the 10k line received `RC0603FR-071KL` (the 1k part) and R3 received the 10k part.
  - A, with a compose that only reverses the line order: R3 received a capacitor MPN (`CL10A106…`) and C1 received a resistor MPN.
  - The current fixtures do not trigger it (0 moved lines on all 6 sample designs). That is why CI is green. Real designs with groups like {C2, C10} or {R2, R10} trigger it in B. Any real-LLM compose that reorders lines triggers it in A.
- Why it matters: it corrupts `acc_mpn`, `mpn_out_of_reference_rate` and coverage for both variants, and production BOMs (customer-facing MPNs on the wrong parts). It also biases A against B, because A's exposure depends on LLM reordering. It also silently overwrites MPNs that A's compose step or B's repair step changed.
- Fix:
  - Give `choices` a resettable reducer, e.g. `def _choices(a, b): return [] if b is None else a + b`, and return `{"choices": None}` from validate.
  - Or drop `apply_choices` from `finish` (choices are always applied in validate, because select_mpn → validate is a fixed edge).
  - Separately, make `group_components` sort by `natural_key` over the natural-sorted refdes, so `renumber` is a no-op.
  - Add a regression test with {R2, R10} and a compose responder that reorders lines.
- Owner-reserved files: no.

### Important

**I1. Error injection: model failures and budget stops are scored as "not detected", and A shares one 900 s wall-clock budget across baseline and all trials.**
- Where: `packages/py/cli/src/bomagent_cli/experiment.py:252-270`, `runtime_base.py:117-132`, `contracts.py:280`.
- What is wrong:
  - One `validation_context` (one `Budget`, started at creation) serves the baseline plus all `trials` validate calls.
  - `llm_validate` goes through `guarded`. A `BudgetExceededError` or `LlmError` returns `[]`, which gives `detection_rate = 0`.
  - If the baseline fails, all of A's later findings count as "new", which inflates false alarms.
  - Injection records carry no status, so failures cannot be told apart from misses.
  - On Mistral Large 4 a validate call takes minutes (#83 commit message), and the call budget for validate is 60 + (8000+6000)/15 → capped at 900 s. Baseline plus 3 trials will exceed `timeout_s=900` cumulatively.
- Why it matters: it systematically deflates A's `detection_rate` (a secondary metric in PREREJESTRACJA §3). B's rules never fail.
- Fix:
  - Create a fresh context (budget) per validate call.
  - Record `status` and `failed`/`budget_hit` per trial in `injection.jsonl`.
  - Exclude failed trials, and the baseline-failed design, from the rates. Report them as counts.
- Owner-reserved files: no.

**I2. The run wall-clock budget (900 s, default `RunConfig`) is shorter than the per-call timeouts #83 introduced, and the budget is not in the manifest.**
- Where: `contracts.py:278-284`, `llm/chat.py:149-161`, `variant_a.py:238` (compose skipped when status != completed), `experiment.py:181-210, 216-233`, `agent-worker/handler.py:350-354`.
- What is wrong:
  - A runs extract_group (16k+6k tokens, so up to 900 s), N× select_mpn, validate (up to 900 s) and compose (900 s) in sequence.
  - `Budget.check` refuses the next call once more than 900 s have elapsed. The run ends `budget_exceeded` with an un-composed BOM.
  - B makes only short mpn_select calls.
  - The experiment never sets `RunConfig`, and `_manifest` does not record `max_llm_calls`, `max_total_tokens`, `timeout_s`, `kb_k`, `concurrency` or `max_repair_iterations`.
- Why it matters:
  - A's F1, cost and statuses then depend on provider latency on the day of the run rather than on the architecture. That confounds H1 and H3.
  - The budget that decides outcomes is not reproducible from `manifest.json` (PREREJESTRACJA §7.3).
  - The worker hits the same limit in production.
- Fix:
  - Make `run_config` (budget fields) part of `ExperimentConfig`, pass it into `RunConfig`, and dump `RunConfig().model_dump()` into the manifest.
  - Set `timeout_s` to at least the sum of the step call budgets (or derive it from the catalogue's `reasoning_tokens`).
  - Record a pre-registered value.
- Owner-reserved files: no.

**I3. Timed-out and 4xx gateway calls are metered as 0 calls, 0 tokens and EUR 0.**
- Where: `llm/chat.py:194-196` (ReadTimeout → `LlmError` without usage), `chat.py:238-240` (status ≥ 400, including 408), `chat.py:102-103`, `runtime_base.py:183`.
- What is wrong: the comment at `runtime_base.py:183` says "failed attempts are paid for too", but for timeouts and 4xx responses the charged usage is empty. #83 shows that long A calls do time out on Mistral, and the provider bills a generation cut off by the gateway.
- Why it matters: it understates A's `cost_eur` and `llm_calls`. `cost_eur` is a primary metric (H3), and the bias favours A in proportion to its timeout rate. Tenant budget metering is also low.
- Fix:
  - At minimum count `llm_calls=1` and an estimated input-token usage (`prompt` length / 4, priced) for timed-out and 408 calls, and flag them (`Usage.estimated` or a finding).
  - Report the number of timed-out calls per variant in `report.md`.
- Owner-reserved files: no.

**I4. Cassette replay of real-model recordings cannot work, and misses silently fall back to the heuristic fake.**
- Where: `llm/chat.py:67-79` (the key includes `model.gateway_model`), `chat.py:292-293` (silent fallback), `cli/main.py:164-173` (cassettes used only when `provider == "fake"`), `experiment.py:223`.
- What is wrong:
  - `bomagent record --model mistral-large-eu` stores keys hashed with `mistral/mistral-large-4-0`.
  - `bomagent run/experiment --cassettes` applies cassettes only to `fake-*` models, whose key hashes `fake-closed`. So every lookup misses and the heuristic responder answers.
  - With a real model id, cassettes are ignored and the gateway is called.
  - The CLI test (`cli/tests/test_cli.py:48-52`) records and replays with the fake only, so this is untested.
- Why it matters: CLAUDE.md rule 7 and the reproducibility claim ("recorded responses") are not achievable for thesis runs. A "replayed" experiment quietly becomes a heuristic run.
- Fix:
  - Allow `--cassettes` with any catalogue model: replay-only `FakeChat` with `responder=None` that raises on a miss, and keep the real `ModelSpec` so the keys match.
  - Fail loudly on a cassette miss in replay mode.
  - Add a test that records with model X and replays with model X.
- Owner-reserved files: no.

**I5. The experiment matrix is not crash-safe: one unexpected exception discards every paid run.**
- Where: `experiment.py:296-334, 388`, `runtime_base.py:120-132`.
- What is wrong:
  - Records live in memory, and `runs.jsonl` is written only by `_write` at the end.
  - `guarded` catches only `BudgetExceededError` and `LlmError`. For example, a `TypeError` from `json.loads` on non-string `content`, a retriever error, or an SDK `CLIConnectionError` propagates out of `asyncio.run` and aborts the whole matrix. There is no per-run try/except and no resume.
- Why it matters: a real-model matrix (designs × 2 variants × repeats, hours and money) can be lost entirely. Re-running it changes the sample, which conflicts with the "analysis run once on the complete matrix" rule (PREREJESTRACJA §7.2).
- Fix:
  - Append each record to `runs.jsonl` as it finishes, write the manifest at the start, and skip finished (design, variant, model, repeat) keys on restart.
  - Wrap `_run_one` and record `status="error"` with the exception type, so failed runs are still reported (§7.1).
- Owner-reserved files: no.

**I6. The `attempted_mpn_hallucination_rate` (primary H2) denominator misses some of A's agent decisions.**
- Where: `metrics.py:379-391`, `variant_a.py:151-176, 255-276`, `claude_sdk_a.py:227-229`.
- What is wrong:
  - `kept` counts only items whose `provenance["mpn"]` is AGENT. In A, `lines_to_items` never sets `mpn` provenance. Compose restores it only when the refdes tuple matches exactly *and* the MPN is unchanged.
  - An MPN that compose changed or added survives without provenance, so it is not in the denominator. A compose rejection is in the numerator.
  - A regrouped or reordered refdes list drops the provenance of a select_mpn decision. Today C1 masks this by re-adding it by line number.
  - For `runtime: claude_agent_sdk_a`, `kept` is always 0, so the rate is exactly 1.0 whenever any MPN is rejected and NaN otherwise.
- Why it matters: it biases H2 against A (the rate is overstated) and makes the metric meaningless for the SDK runtime.
- Fix:
  - Set `mpn`/`manufacturer` provenance to the compose (or submit_bom) agent whenever compose emits a non-empty MPN that did not come from the parser. Match the previous provenance by refdes *set*, not by tuple.
  - Add a unit test that compose-introduced MPNs count as decisions.
- Owner-reserved files: no.

**I7. Agent-worker: LLM spend is not metered when a run raises inside the runtime.**
- Where: `services/agent-worker/src/bomagent_agent_worker/handler.py:263-277, 361`.
- What is wrong: `spent["usage"]` is set only after `_invoke` returns. Any non-LLM exception in the graph (for example a `KbRetriever` DB error in `choose_mpn`) goes to `_fail(..., spent.get("usage")=None)`, which meters 0 calls and EUR 0 although earlier LLM calls were paid.
- Why it matters: tenant budget and metering are understated in production.
- Fix: expose the context's running usage (for example via the `on_step` callback, which already receives `budget.usage`) and store the last value in `spent` on every step.
- Owner-reserved files: no.

### Minor

**M1. The Holm family shrinks when a primary p-value is NaN.**
- Where: `experiment_stats.py:64-75`, `experiment.py:355`.
- What is wrong: PREREJESTRACJA §4 fixes 3 hypotheses per model. `holm_adjust` drops NaN entries from `m`. `attempted_mpn_hallucination_rate` is NaN when B makes no agent MPN decisions, so the correction then uses m=2 and is less conservative than registered.
- Fix: use m = len(PRIMARY_METRICS) (`m=3`) always, or record the shrink as a deviation in §8.

**M2. Design MPNs are read inconsistently for the residual metric.**
- Where: `experiment.py:302`.
- What is wrong: `design_mpns` reads only `c.field("MPN")`, but the guard (`registry.py:34-37`) also accepts "Manufacturer Part Number". A parser MPN under that field name is trusted by the guard but counted as "unverified" by the residual `mpn_hallucination_rate`.
- Fix: reuse the same helper in both places.

**M3. `false_alarm_rate` is a false-discovery proportion and rewards silence.**
- Where: `injection.py:81-83`.
- What is wrong: it is 0.0 when a validator raises no new findings.
- Fix: return NaN when `new_findings == 0`, and name or document it as FDR.

**M4. The manifest is written after the matrix finishes, and the commit has no dirty flag.**
- Where: `experiment.py:153-163, 471`.
- What is wrong: `commit`, `created_at`, the catalogue and the KB hash reflect the state *after* a multi-hour run. Uncommitted code changes are not detected.
- Fix: build the manifest before the first run and add `git status --porcelain` (dirty: bool).

**M5. The SDK runtime cost ignores prompt-cache tokens.**
- Where: `claude_sdk_a.py:181-209`.
- What is wrong: `cache_creation_input_tokens` is dropped entirely and `cache_read_input_tokens` is not priced. That understates cost for a 40-turn loop.
- Note: this is relevant only if this runtime is used in the experiment.

**M6. Empty model content is accepted as an answer.**
- Where: `llm/chat.py:243`.
- What is wrong: `content or "{}"` with `finish_reason` unchecked means an empty or length-truncated reply validates as an all-default `MpnChoice` ("no MPN") instead of a failure. This matters for reasoning models that use up `max_tokens`.
- Fix: treat `finish_reason == "length"` or empty content as an `LlmError` (with usage).

**M7. The per-variant CIs bootstrap over runs.**
- Where: `experiment.py:495-501` (`variants.csv`) and the `_report` table at lines ~698-705.
- What is wrong: repetitions of one design are treated as independent, which contradicts the design-as-unit rule.
- Fix: use `cluster_bootstrap_ci` over designs, or label these CIs as descriptive.

**M8. Whitespace-only differences in a chosen MPN are counted as hallucination attempts.**
- Where: `variant_b.py:79-81`.
- What is wrong: `allowed`/`choice.mpn.upper()` are not stripped, while `evidence_mpns` is (line 58). A model reply with a stray space counts as an attempted hallucination.
- Fix: normalise both sides with `norm_mpn`.

**M9. The Mistral Large 4 prices are placeholders while the entry is enabled and verified.**
- Where: `llm/catalog/models.yaml:201-211`.
- What is wrong: the notes say the prices are Large 3 list prices to recheck. H3 (`cost_eur`) depends on the in/out price ratio, because A is output-heavy through reasoning.
- Fix: confirm the prices before the `prereg-v1` freeze, or record them as a known deviation.

**M10. Results are keyed by `design.design_name`.**
- Where: `experiment.py:300-320`.
- What is wrong: two directories with the same design name (e.g. `evals/samples/ecg-frontend` and `evals/fixtures/kicad/ecg-frontend`) would be merged into one statistical unit.
- Fix: key by the directory path, or reject duplicate names in `ExperimentConfig`.

None of the issues touch owner-reserved files (auth.py, authz.py, sso.py, migrations, RLS, deploy/*, web session handling).

## Declined to judge
- Whether LiteLLM normalises Mistral Large 4 reasoning output to a string `content`. If it ever returns a list of chunks, `json.loads` raises `TypeError` (not caught at chat.py:258-261). I could not verify this without the gateway.
- Correctness of KB RLS and global/tenant scope in `kb/store.py`. It was out of depth for this pass, and the RLS migrations are owner-reserved.
- The actual pilot gateway deployment (`deploy/gateway`, `deploy/supabase/gateway.fly.toml`, #81) beyond what `gateway_config.render` produces (owner-reserved deploy/*).
- Whether a run-level timeout of 900 s is a deliberate "same budget" design choice. I1 and I2 flag only that it is unrecorded and interacts with the #83 per-call budgets.
- The quality of the LLM prompts themselves (`prompts/*.md`).
