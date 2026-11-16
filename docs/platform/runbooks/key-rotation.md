# Runbook: keys and secrets of the Fly.io + Supabase pilot (inventory and rotation)

All steps are done by a **human** (CLAUDE.md rule 6). Secrets live only in `fly secrets` (Fly's
encrypted store) and in the owner's password manager - never in the repository, a chat, a shell
history or a file on disk. `<...>` = placeholder. Audit finding SEC-08.

> The LiteLLM admin calls used by `tools/pilot-llm-key.sh` (`/key/generate`, `/key/delete`) were
> written against LiteLLM's documented API and exercised only against test doubles. After
> bumping the pinned image (`deploy/docker/llm-gateway.Dockerfile`) run the script once on a
> throwaway alias and check `fly logs -a mgr-ibm-llm-gateway`.

## Inventory

| Secret | Stored in | Used by | Rotate every | How |
|---|---|---|---|---|
| App virtual key (`BOMAGENT_LLM_GATEWAY_KEY`) | Fly secret, app `mgr-ibm-bomagent` | the app -> gateway | 90 days (key expires) | section 1 |
| Gateway master key (`LITELLM_MASTER_KEY`) | Fly secret, app `mgr-ibm-llm-gateway`; password manager | creating/rotating virtual keys | 180 days, after any stop-gap use, on suspicion | section 2 |
| Provider keys (Mistral, Azure OpenAI, AWS IAM key of `bomagent-llm-gateway`) | Fly secrets on the gateway app | gateway -> providers | 180 days | section 3 |
| Database role passwords (`bomagent_migrator`, `bomagent_app`, `bomagent_platform`) | Fly secrets on the main app; password manager | the app | 180 days | section 4 |
| Supabase database admin (`postgres`) password | password manager | bootstrap / maintenance only | 180 days | Supabase -> Connect -> Reset database password |
| Supabase Storage S3 access key | Fly secrets on the main app (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) | file storage | 180 days | section 5 |
| Audit anchor sink credentials | wherever `BOMAGENT_AUDIT_ANCHOR_*` points (SEC-04) | the maintenance job | 180 days | like section 5, for that bucket |
| Fly deploy / API tokens | password manager | `fly deploy` from a laptop or CI | 90 days | `fly tokens create` then revoke the old one |

Rule of thumb for every rotation: **create the new secret, switch the consumer, verify, only then
revoke the old one.** Never revoke first.

## 1. App virtual key (routine, 90 days)

1. `tools/pilot-llm-key.sh --alias bomagent-pilot-$(date +%Y%m%d)` - asks for the master key
   silently, creates a key limited to the models the gateway serves (budget 20 EUR, 90 days by
   default; `--budget`, `--duration`), stores it as `BOMAGENT_LLM_GATEWAY_KEY` of the main app
   through stdin. The app restarts.
2. Verify: `curl -s https://mgr-ibm-bomagent.fly.dev/readyz` shows `"llm":"gateway"`; start one
   run.
3. Retire the previous key (or let it expire): `tools/pilot-llm-key.sh --delete-only
   --delete-alias <old alias>`.

Stop-gap (using the master key as the app key) is not supported by the script and must not be
used longer than the first smoke test: it can administer the gateway. If it was used, do
section 2 right after.

## 2. Gateway master key

1. Generate: `openssl rand -hex 32` (prefix `sk-`). Save it in the password manager first.
2. `fly secrets set -a mgr-ibm-llm-gateway LITELLM_MASTER_KEY="sk-<new>"` (restarts the gateway;
   the app gets 5xx for the restart, about a minute).
3. Check that virtual keys still work (`/readyz` of the app and one run). **Caution:** LiteLLM
   derives the encryption of provider credentials and virtual keys stored in its database from
   its salt; if no separate `LITELLM_SALT_KEY` is configured, changing the master key can make
   stored keys unreadable. Before the first rotation read the LiteLLM documentation for the
   pinned version and set a dedicated salt (`fly secrets set LITELLM_SALT_KEY=...`) once, **before**
   creating the first virtual key. If virtual keys stop working after a rotation, recreate the app
   key with section 1.
4. Remove the old master key from the password manager.

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

1. Generate three new passwords (letters and digits only): `openssl rand -hex 24` each; save them
   in the password manager.
2. In the Supabase SQL editor (as `postgres`): `ALTER ROLE bomagent_app PASSWORD '<new>';` and the
   same for `bomagent_platform` and `bomagent_migrator`. (Re-running `python -m bomagent_allinone
   bootstrap`, see `supabase-pilot.md`, is the alternative; check it with a test login afterwards.)
3. `fly secrets import -a mgr-ibm-bomagent` with `BOMAGENT_DATABASE_PASSWORD`,
   `BOMAGENT_PLATFORM_DATABASE_PASSWORD` and `BOMAGENT_MIGRATOR_DATABASE_URL` (stdin, one line per
   secret). The app restarts with the new passwords; between 2 and 3 new connections fail - do it
   in a quiet minute.
4. Verify `/readyz`. The local file `~/.mgr-ibm-pilot-secrets.env` written by
   `tools/pilot-setup.sh` holds the old values: delete it once they are in the password manager.

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
