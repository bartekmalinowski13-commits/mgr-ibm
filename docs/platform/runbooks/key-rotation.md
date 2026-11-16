# Runbook: keys and secrets of the Fly.io + Supabase pilot (inventory and rotation)

All steps are done by a **human** (CLAUDE.md rule 6). Secrets live only in `fly secrets` (Fly's
encrypted store) and in the owner's password manager - never in the repository, a chat, a shell
history or a file on disk (one exception remains until section 4 is done once:
`~/.mgr-ibm-pilot-secrets.env`, and the old `~/.mgr-ibm-llm-secrets.env`). `<...>` = placeholder. Audit finding SEC-08.

> The LiteLLM admin calls used by `tools/pilot-llm-key.sh` (`/key/generate`, `/key/delete`) were
> written against LiteLLM's documented API and exercised only against test doubles. After
> bumping the pinned image (`deploy/docker/llm-gateway.Dockerfile`) run the script once on a
> throwaway alias and check `fly logs -a mgr-ibm-llm-gateway`.

## Inventory

| Secret | Stored in | Used by | Rotate every | How |
|---|---|---|---|---|
| App virtual key (`BOMAGENT_LLM_GATEWAY_KEY`) | Fly secret, app `mgr-ibm-bomagent` | the app -> gateway | 60-75 days (the key expires after 75 days by default) | section 1 |
| Gateway master key (`LITELLM_MASTER_KEY`) | Fly secret, app `mgr-ibm-llm-gateway`; password manager | creating/rotating virtual keys | 180 days, after any stop-gap use, on suspicion | section 2 |
| Provider keys (Mistral, Azure OpenAI, AWS IAM key of `bomagent-llm-gateway`) | Fly secrets on the gateway app | gateway -> providers | 180 days | section 3 |
| Gateway database (`DATABASE_URL` of the `litellm` role, runbook `llm-gateway-pilot.md` step 5) | Fly secret on the gateway app; password manager | the gateway (virtual keys, budgets) | 180 days | like section 4: change the role password, then `fly secrets import` the new URL |
| Gateway salt (`LITELLM_SALT_KEY`), if one is configured | Fly secret on the gateway app; password manager | the gateway (encrypts credentials stored in its database) | **never change it** | see section 2 |
| Database role passwords (`bomagent_migrator`, `bomagent_app`, `bomagent_platform`) | Fly secrets on the main app; password manager | the app | 180 days | section 4 |
| Supabase database admin (`postgres`) password | password manager | bootstrap / maintenance only | 180 days | Supabase -> Connect -> Reset database password |
| Supabase Storage S3 access key | Fly secrets on the main app (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) | file storage | 180 days | section 5 |
| Audit anchor sink credentials | wherever `BOMAGENT_AUDIT_ANCHOR_*` points (SEC-04) | the maintenance job | 180 days | like section 5, for that bucket |
| Fly deploy / API tokens | password manager | `fly deploy` from a laptop or CI | 90 days | `fly tokens create` then revoke the old one |

Rule of thumb for every rotation: **create the new secret, switch the consumer, verify, only then
revoke the old one.** Never revoke first.

## 1. App virtual key (routine, every 60-75 days)

1. `tools/pilot-llm-key.sh --alias bomagent-pilot-$(date +%Y%m%d)` - asks for the master key
   silently, creates a key limited to the models the gateway serves, with a **lifetime** budget
   (20 by default, in the unit LiteLLM counts - US dollars - not per month) and an expiry
   (75 days; `--budget`, `--duration`), stores it as `BOMAGENT_LLM_GATEWAY_KEY` of the main app
   through stdin. The app restarts. Two consequences: when the budget is used up or the key
   expires the app gets 4xx errors from the gateway until you rotate, so rotate well before
   (60-75 days) and watch the spend; and the key only covers the models enabled **today** - after
   enabling more models in the catalogue, rotate the key.
2. Verify: `curl -s https://mgr-ibm-bomagent.fly.dev/readyz` shows `"llm":"gateway"`; start one
   run.
3. Retire the previous key (or let it expire): `tools/pilot-llm-key.sh --delete-only
   --delete-alias <old alias>`.

Stop-gap (using the master key as the app key) is not supported by the script and must not be
used longer than the first smoke test: it can administer the gateway. If it was used, do
section 2 right after.

## 2. Gateway master key

1. Generate: `openssl rand -hex 32`, prefix `sk-`. Save it in the password manager first.
2. Set it without putting it on a command line (shell history, `ps`):
   `read -r -s -p "new master key: " K; echo; printf 'LITELLM_MASTER_KEY=%s\n' "$K" | fly secrets import -a mgr-ibm-llm-gateway; unset K`
   The gateway restarts; the app gets 5xx for about a minute.
3. Verify with `/readyz` of the app and one run. Virtual keys are stored in the gateway's
   database as hashes and keep working; if they do not, recreate the app key with section 1.
4. Remove the old master key from the password manager.

**Salt - read before the first rotation.** From LiteLLM's documentation (not verified against the
pinned version here): credentials that LiteLLM stores *encrypted in its database* (for example
models added through its UI) are encrypted with a salt that defaults to the master key. This
gateway takes provider keys from Fly secrets and the rendered config, so little or nothing may be
stored that way - check in the LiteLLM UI/DB before rotating. Do **not** invent a fresh
`LITELLM_SALT_KEY` on a gateway that already holds encrypted data: the salt must equal the master
key in use when that data was written (or be set before any exists) and must never change
afterwards. If you want the master key to be rotatable without that coupling, set
`LITELLM_SALT_KEY` to the **current** master key now, then rotate.

## 3. Provider keys

- **Mistral:** console.mistral.ai -> create a second API key -> `fly secrets set -a
  mgr-ibm-llm-gateway MISTRAL_API_KEY=<new>` -> test a run -> delete the old key in the console.
- **Azure OpenAI:** regenerate "Key 2", set `AZURE_API_KEY=<key 2>`, test, regenerate "Key 1".
- **AWS (Bedrock):** IAM -> user `bomagent-llm-gateway` -> create a second access key, set
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, test, then deactivate and delete the old key.
  Keep the EU-only policy of runbook `llm-gateway-pilot.md` (A.3) on the user.
- Always `fly secrets set` with the value read from the password manager; do not paste keys into
  commands that stay in shell history (use `fly secrets import` with stdin, as the setup script does).

## 4. Database role passwords

The old password stops working when the role is changed, so do steps 2-3 back to back in a quiet
minute (new connections from the app fail in between; open ones persist).

1. Generate three new passwords (letters and digits only): `openssl rand -hex 24` each; save them
   in the password manager. Prepare the three secret lines first (below), so step 3 is one paste.
2. In the Supabase SQL editor (as `postgres`): `ALTER ROLE bomagent_app PASSWORD '<new>';` and the
   same for `bomagent_platform` and `bomagent_migrator`. The editor keeps query history: delete
   these entries afterwards. (Alternative: re-run `python -m bomagent_allinone bootstrap` as in
   `supabase-pilot.md`; check with a test login that it resets existing passwords.)
3. Immediately: `fly secrets import -a mgr-ibm-bomagent` with, on stdin,
   `BOMAGENT_DATABASE_PASSWORD=<app>`, `BOMAGENT_PLATFORM_DATABASE_PASSWORD=<platform>` and the
   **complete URL** `BOMAGENT_MIGRATOR_DATABASE_URL=postgresql+psycopg://bomagent_migrator.<REF>:<migrator>@<POOLER>:5432/bomagent?sslmode=require`
   (see `supabase-pilot.md`). The app restarts with the new passwords.
4. Verify `/readyz`. The files `~/.mgr-ibm-pilot-secrets.env` (written by `tools/pilot-setup.sh`)
   and `~/.mgr-ibm-llm-secrets.env` (written by an earlier version of
   `tools/pilot-llm-setup.sh`, it holds the old master key) hold old values: once everything is in
   the password manager, delete both (`shred -u` or plain `rm`).

## 5. Supabase Storage S3 key (and any other S3 key)

1. Supabase -> Storage -> S3 connection -> **New access key**; save id and secret.
2. `fly secrets import -a mgr-ibm-bomagent` with `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
3. Verify: upload a file in the app, download the BOM. Then delete the old access key in Supabase.

## If a key leaked

1. Revoke at the source first (provider console / Supabase / `fly tokens revoke`), then rotate as
   above. For the app virtual key: delete it in the gateway (`--delete-alias`) - it is limited to
   the pilot budget, so the damage is bounded, which is the point of not using the master key.
2. Look at the provider's usage page for the time window; the app's own record is the audit log
   (`/v1/audit-events`) and the per-run usage.
3. Write down what leaked, when and what you did (a `DECISIONS_LOG` row). A breach involving
   personal data has a 72-hour notification duty under GDPR (see the incident runbook once written,
   audit OPS-06).
