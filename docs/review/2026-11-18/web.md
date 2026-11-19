# Code review: web app (apps/web, packages/ts/*)

Reviewed at `origin/main` f704a8f. Gates I ran in a temporary worktree (since removed): `vitest` 18 files / 104 tests passed, `tsc --noEmit` clean, `biome check` clean (it only says the config should be migrated). Playwright e2e was not run because it needs the full local stack.

## Strengths
- **No XSS sinks.** There is no `dangerouslySetInnerHTML`, `innerHTML`, `eval` or `target=_blank` anywhere. Untrusted content (file names, BOM fields, KB citations/quotes, server `error` strings, SSO status text) is always rendered as React text.
- **Tenant-scoped caching.** Every query key that holds tenant data includes `orgId`, and switching organisation calls `queryClient.clear()` (Shell.tsx:57, OnboardingScreen.tsx:28). `X-Org-Id` is injected centrally by api-client middleware and also by the multipart helpers.
- **Error slugs are guarded by a test.** problems.test.ts reads every `slug="..."` in services/api and checks that PL and EN both have a message for it, and that the two sets of error keys match.
- **Good accessibility baseline.**
  - Status uses icon plus text, never colour alone (`StatusBadge`).
  - `prefers-reduced-motion` is honoured.
  - A token contrast test exists (a11y.test.ts).
  - The ItemPanel manages focus and traps Tab in drawer mode.
  - Sortable headers use `aria-sort`, and the scroll region in ReferencePanel is keyboard reachable.
  - Playwright runs axe (WCAG 2.2 AA tags) across the main flows.
- **Auth flow hygiene.** OIDC PKCE uses state and nonce checks. The recovery token stays in memory only and the fragment is stripped from the URL right away. Idempotency keys are sent on creating POSTs.
- **Good list states on several screens.** Projects, Runs, KB, Audit and Members each have explicit loading, error and empty states, with retry where it makes sense.

## Issues

### Critical
None found.

### Important

**I-1. `problemMessage()` throws a TypeError for any error body that is not RFC 9457. Every error path then breaks.**
- **Where:**
  - apps/web/src/lib/api.ts:141 (`error.problem.type.split(...)`)
  - api.ts:20-24 (`call()`)
  - api.ts:41-43, 57-59, 68-70, 75, 81 (multipart helpers and downloads)
  - packages/ts/api-client/src/index.ts:53 (`unwrap`)
- **What is wrong:**
  - On a non-JSON body (502/504 HTML from a proxy, or a 413 from the edge), openapi-fetch hands back the raw text as `error`. On an empty body it hands back `""`. `call()` casts either one to `Problem`, so `problem.type` is `undefined`.
  - I reproduced this with a throwaway vitest. Both a `"<html>502</html>"` body and an empty 503 body make `problemMessage` throw `TypeError: Cannot read properties of undefined (reading 'split')`.
  - The multipart helpers call `await resp.json()` before checking `resp.ok`. A non-JSON error therefore surfaces as a raw `SyntaxError: Unexpected token '<'…` string in the toast.
- **Why it matters:**
  - `LoadError` (common.tsx:79) calls `problemMessage` during render. The screen crashes into TanStack Router's default boundary, which shows untranslated English and has no retry, and no `defaultErrorComponent` is configured (router.tsx:121).
  - In every mutation `catch`, the toast/setError call itself throws. The user gets no feedback and an unhandled rejection is raised.
  - Large CAD uploads that hit a gateway size limit are exactly this case. This breaks UX §5/§6 ("errors say what happened and how to fix it").
- **Fix:**
  - In `call()` and the helpers, normalise the error body: if it is not an object with a string `type`, build `{type: "about:blank", title: statusText, status}`. Parse JSON only when the content-type is `application/(problem+)json`.
  - Make `problemMessage` defensive (`error.problem?.type?.split(...)`) and map status codes to generic localised messages (`errors.http.5xx`, `errors.http.413`).
  - Add `defaultErrorComponent` to the router using `LoadError`.
  - Add tests for HTML, empty and plain-JSON error bodies.
- **Owner-reserved:** no.

**I-2. "Both variants" can create duplicate, billable runs, and the idempotency key is useless for retries.**
- **Where:** apps/web/src/screens/NewRunDialog.tsx:94-106. The same pattern is in ProjectsScreen.tsx:20-24 and RunScreen.tsx:116.
- **What is wrong:**
  - The keys come from `idempotencyKey()`, called inside the submit or click handler, so every attempt gets a fresh key.
  - With "both", A is POSTed and then B. If B fails (quota, budget-exceeded, 5xx), A has already been created but the dialog stays open with the error. Pressing "Run" again creates a second A run.
  - ProjectsScreen `create` has no busy guard, so a double submit creates two projects.
- **Why it matters:** each duplicate run spends LLM budget, which is metered against quota. It also pollutes the thesis run set (repeatable experiment).
- **Fix:**
  - Generate one key per variant when the dialog mounts (`useState(() => ({A: idempotencyKey(), B: idempotencyKey()}))`) and reuse it on resubmit.
  - Remember which variants already succeeded and skip them on retry, or say so in the error.
  - Disable submit while busy in ProjectsScreen.
- **Owner-reserved:** no.

**I-3. The comparison screen says the variants are identical when a BOM fails to load.**
- **Where:** apps/web/src/screens/CompareScreen.tsx:61-64, 170-173, 79-110.
- **What is wrong:**
  - `diffs` is `[]` unless both BOMs have data. `bomA.isError` / `bomB.isError` are never checked.
  - After the pending check, an error falls through to `disagree.length === 0` and renders `compare.same` ("no differences"). The metrics table shows 0 lines and 0 findings for the failed side.
  - If a variant has no completed run (reachable via a direct URL with two B runs), `useBom(undefined)` stays disabled. `isPending` is then true forever, so the skeleton never goes away.
- **Why it matters:** this is the thesis A/B comparison screen. A silent "no differences" is a wrong result, not just a missing error state.
- **Fix:**
  - Render `<LoadError>` (with retry) when either BOM query errors.
  - Use `bomX.isLoading` or `fetchStatus` rather than `isPending` for disabled queries.
  - Show `compare.needTwo` when `runA` or `runB` is undefined.
  - Add a component test for the error case.
- **Owner-reserved:** no.

**I-4. Irreversible admin actions run without confirmation.**
- **Where:** apps/web/src/screens/SettingsScreen.tsx:
  - remove member :145-161
  - role change on select :125-136
  - revoke invitation :208-224
  - remove SSO domain :347-361
  - remove SSO provider :498-509
  - rotate API key :588-607
  - revoke API key :608-624
- **What is wrong:**
  - One click immediately removes a member, revokes or rotates an API key (breaking integrations), or deletes the SSO provider.
  - Changing your own role in the select applies at once and can drop your own admin access.
  - Project and file deletion do confirm (ProjectScreen.tsx:57,71), so the app is inconsistent.
  - The revoke toast reuses the button label `settings.revoke` ("Revoke"). UX §5 wants the past tense ("Key revoked").
- **Why it matters:** an accidental click on a security setting cannot be undone. This also goes against UX copy rules.
- **Fix:**
  - Confirm before each of these actions (reuse `window.confirm` with i18n strings, or a Radix alert dialog). Name the target in the prompt, e.g. "Revoke key ‘ci-bot’? Integrations using it stop working."
  - Use dedicated past-tense toast keys (`settings.revoked`, `settings.keyRevoked`).
- **Owner-reserved:** touches the SSO and API key UI, not session handling. Partly owner-reserved: SSO.

**I-5. The mobile/narrow navigation drawer is not keyboard accessible.**
- **Where:** apps/web/src/screens/Shell.tsx:331-343, 346-353.
- **What is wrong:**
  - Below `lg`, the drawer opens without moving focus into it.
  - There is no Escape handling, no focus trap and no `role="dialog"` / `aria-modal`.
  - The page behind it stays in the tab order.
  - The hamburger has no `aria-expanded` / `aria-controls`, and focus is not returned to it when the drawer closes.
- **Why it matters:** WCAG 2.4.3 (focus order) and 2.1.1 (keyboard). The drawer layout also applies on desktop at 200% zoom, which keyboard and low-vision users rely on. axe does not catch this, and mobile.spec.ts never opens the drawer.
- **Fix:** render the drawer with the existing Radix `Dialog` primitives (packages/ts/ui/src/dialog.tsx) or `@radix-ui/react-dialog` directly. That gives the focus trap, Escape and focus return for free. Add `aria-expanded` to the trigger and a Playwright keyboard test.
- **Owner-reserved:** no.

### Minor

**M-1. Stale per-run state after "Rerun" (the component is not remounted on a param change).**
- **Where:** apps/web/src/screens/RunScreen.tsx:52, 60, 121.
- **What is wrong:**
  - TanStack Router keeps the component mounted (`remountDeps` is not set), so `live` and `selected` survive navigation to `/runs/<newId>`.
  - If the user watched run X finish, run Y starts with `status="completed"` until its first SSE event. During that window it shows a "Done" badge, Rerun and Export buttons for a queued run, and fires `GET /bom`, which returns `no-bom` and flashes an error.
  - `selected` re-opens the item panel on the same line number of the new BOM.
- **Fix:** reset with `useEffect(() => { setLive(undefined); setSelected(undefined); }, [runId])`, or set `remountDeps: ({params}) => params` on `runRoute`.

**M-2. The live view can freeze when the SSE stream ends without an `end` event.**
- **Where:** RunScreen.tsx:67-74 and api.ts:122.
- **What is wrong:**
  - `streamRun` returns `undefined` on non-ok responses. The server also closes the stream silently after `sse_timeout_s=900`.
  - The client invalidates the run once. It only reconnects if the refetched run object changes. Errors are swallowed (`.catch(() => undefined)`) and the run query has no polling fallback.
- **Fix:** while not terminal, add `refetchInterval` (for example 5 s) to the `run` query. Or reconnect with backoff whenever the stream ends without a terminal status.

**M-3. Missing error states that show as empty or loading instead.**
- **Where:**
  - ProjectScreen.tsx:187-222: a `files` error shows "no files".
  - ProjectScreen.tsx:241-245: a `runs` error shows "no runs".
  - SettingsScreen.tsx:197-230: an invitations error shows "no pending".
  - SettingsScreen.tsx:570-630: API keys show "no keys" while loading and on error.
  - StartScreen.tsx:26-48: stats show empty-state invitations while loading or on error.
  - NewRunDialog.tsx:459-485: shows "no projects – create one" while projects load.
  - NewRunDialog.tsx:523-533: a models error leaves an empty select and a disabled submit with no message.
  - SettingsScreen.tsx:710-711: a `me` error shows "not a member".
  - Shell.tsx:183-195: a `/v1/me` error is never shown. With no stored org, every `enabled: !!orgId` query stays pending, so skeletons spin forever.
- **Why it matters:** UX §6 says every list needs an error and empty state.
- **Fix:** handle `isPending` / `isError` explicitly with `Skeleton` / `LoadError` everywhere.

**M-4. Polish and English plurals are missing.**
- **Where:** `projects.components`, `projects.uploaded`, `run.findings`, `history.lines`, `bom.csvCopied`, `audit.verifyOk`, `samples.added` in both src/locales/pl.json and en.json.
- **What is wrong:** these keys are single forms used with `count`. The result is "1 components", "Uploaded 1 files", "Wgrano 1 plików", "1 komponentów", "2 pozycji".
- **Fix:** add `_one/_other` (EN) and `_one/_few/_many/_other` (PL), as already done for `kb.chunks`. Extend problems.test.ts so it asserts that every key called with `count` has the plural suffixes.

**M-5. Hard-coded or untranslated UI strings.**
- common.tsx:46: the "Status" column header is literal English.
- AuditScreen.tsx:223-227 and :277: object-type filter options and cells show raw identifiers (`api_key`, `invitation`).
- VersionHistory.tsx:337 and ReferencePanel.tsx:495: field names are raw (`mpn`, `footprint`) although `bom.columns.*` translations exist.
- **Fix:** use `t("run.statusColumn")`, `t("audit.objects.<type>")` and `t("bom.columns.<field>")`.

**M-6. Settings and KB tabs only partly follow the ARIA tabs pattern.**
- **Where:** SettingsScreen.tsx:715-740, KbScreen.tsx:61-77.
- **What is wrong:** they use `role="tablist"` / `tab` / `tabpanel`, but there is no arrow-key navigation, no roving `tabIndex`, no `id` / `aria-controls` on tabs, and no `aria-labelledby` on the panel.
- **Fix:** implement the WAI-ARIA tabs keyboard model, or use `@radix-ui/react-tabs`, copied into packages/ts/ui per ADR-0014.

**M-7. Non-text and placeholder contrast fall below WCAG minimums.**
- The input border `--color-line` #d3d9df on white is 1.42:1. WCAG 1.4.11 wants 3:1 for the boundary of a control that has no other indicator (packages/ts/ui/src/field.tsx:11).
- Placeholder `text-muted/70` on white is 3.22:1, below 4.5:1. The invite-token field relies on the placeholder visually (OnboardingScreen.tsx:76-78).
- a11y.test.ts only checks the solid tokens.
- **Fix:** darken the control border (for example `#8a96a3`, which is at least 3:1), use full `text-muted` for placeholders, and add both pairs to the token test.

**M-8. ItemPanel keeps a stale error and has no busy guard.**
- **Where:** ItemPanel.tsx:79-98, 236.
- **What is wrong:**
  - A successful save does not clear an earlier `error`, so the red alert stays next to the "saved" toast.
  - There is no busy state, so a double submit creates two BOM versions.
  - The Escape handler is global on `window` (:72-75), so Escape in another dialog also closes the panel.
- **Fix:**
  - Call `setError(undefined)` at the start of `save` and on success.
  - Add `busy` and disable submit while it is set.
  - Scope Escape to `panelRef` or check `e.defaultPrevented`.

**M-9. Session teardown keeps the previous user's tenant data in memory, and there is no expiry handling in OIDC mode.**
- **Where:** Shell.tsx:304-314 and session.tsx:86-91.
- **What is wrong:**
  - Sign-out does not call `queryClient.clear()`. In local and Supabase modes there is no reload, so cached projects, BOMs and audit data stay in memory for the tab.
  - In OIDC mode the ID token is never refreshed. After expiry every call fails with `invalid-token` and the user is not sent back to /login.
- **Fix:**
  - Call `queryClient.clear()` on sign-out.
  - Add a global `QueryCache` / `MutationCache` `onError` that signs out and redirects on 401 `invalid-token` / `reauth-required`.
- **Owner-reserved:** yes (web session handling and auth).

**M-10. UX guideline gaps.**
- The audit log has only an object-type filter. UX §4.8 asks for filters by user and time plus export (AuditScreen.tsx).
- KB citations have no link to the datasheet page (UX §4.5; ItemPanel.tsx:494-505).
- Uploads give no format-limitation feedback before the upload (UX §4.2).
- These are spec gaps, not bugs. Log them in DECISIONS_LOG or ROADMAP if they are deferred on purpose.

**M-11. Test coverage gaps.**
- There are no unit or component tests for:
  - NewRunDialog (the "both" partial failure)
  - RunScreen (SSE lifecycle, rerun reset)
  - the `streamRun` SSE parser
  - the `uploadFile` / `evaluateRun` error paths
  - CompareScreen error states
  - SettingsScreen
  - KbScreen
  - AuditScreen
- The audit screen and the API-keys / usage tabs are never visited by Playwright, so axe never checks them.
- Add focused vitest component tests with a mocked `fetch` for I-1 to I-3, M-1 and M-2, and add Audit and Settings tabs to an e2e spec with `expectAccessible`.

## Declined to judge
- Visual design quality and Mobbin/Homerun fidelity (needs screenshots and a running stack). Whether the e2e/axe suite currently passes (not run, as the stack is needed).
- Whether `aria-selected` on focusable `<tr>` rows in a plain `<table>` (BomTable.tsx:279) passes axe. ARIA formally scopes it to grid/treegrid. The axe e2e run would show this.
- Supabase login internals (lib/supabase.ts, SupabaseLogin.tsx, AuthReturnScreens.tsx) beyond scanning them for XSS and redirect sinks (none found). These are owner-reserved, and correctness against Supabase behaviour needs the live provider.
- Server-side behaviour that the UI relies on (last-owner protection on self-demotion, validation of a project with no parsed files in `POST /v1/runs`). Out of this area.
