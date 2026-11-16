#!/usr/bin/env bash
# LLM gateway of the Supabase pilot: create the Fly app and set the provider secrets
# (runbook: docs/platform/runbooks/llm-gateway-pilot.md, steps 4 and 6; the owner guide in
# Polish: docs/owner-guides/KLUCZE_LLM_KROK_PO_KROKU.md).
# Run it yourself in a terminal. Every key is asked silently (nothing is echoed or logged);
# press Enter to skip a provider you do not have yet. Re-run it any time to add providers.
# It does NOT deploy and does NOT touch the main app: Claude Code does that after the
# models are enabled in the catalogue (step 8) and the gateway image is built.
# Nothing secret is written to disk: the gateway master key is generated once, set as a Fly
# secret and shown ONCE in this terminal (save it in your password manager). The app does not
# use the master key: create its limited virtual key with tools/pilot-llm-key.sh.
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
GATEWAY_APP="mgr-ibm-llm-gateway"
MAIN_APP="mgr-ibm-bomagent"

command -v fly >/dev/null || { echo "flyctl not found: brew install flyctl && fly auth login"; exit 1; }
fly auth whoami >/dev/null || { echo "Not signed in to Fly: run fly auth login"; exit 1; }

ask() { # ask VAR "prompt"  (silent; empty = skip)
  local v; read -r -s -p "$2 (Enter = skip): " v; echo; printf -v "$1" '%s' "$v"
}

ask MISTRAL_API_KEY "Mistral API key (console.mistral.ai)"
ask AZURE_API_KEY "Azure OpenAI key"
AZURE_API_BASE=""
if [ -n "$AZURE_API_KEY" ]; then
  read -r -p "Azure OpenAI endpoint (https://<resource>.openai.azure.com): " AZURE_API_BASE
fi
ask AWS_ACCESS_KEY_ID "AWS access key ID (IAM user bomagent-llm-gateway)"
AWS_SECRET_ACCESS_KEY=""
if [ -n "$AWS_ACCESS_KEY_ID" ]; then ask AWS_SECRET_ACCESS_KEY "AWS secret access key"; fi

if [ -z "$MISTRAL_API_KEY$AZURE_API_KEY$AWS_ACCESS_KEY_ID" ]; then
  echo "No key given - nothing to do."; exit 0
fi


if ! fly apps list --json | grep -q "\"Name\": *\"${GATEWAY_APP}\""; then
  ORG="$(fly apps list --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((a.get("Organization",{}).get("Slug","personal") for a in d if a["Name"]=="'"${MAIN_APP}"'"), "personal"))')"
  echo "== creating Fly app ${GATEWAY_APP} in organisation ${ORG} (same as ${MAIN_APP})"
  fly apps create "$GATEWAY_APP" --org "$ORG"
fi

# the master key lives only in Fly's secret store: an existing one is never replaced here
# (rotation: docs/platform/runbooks/key-rotation.md)
NEW_MASTER=""
if ! LISTING="$(fly secrets list --app "$GATEWAY_APP" --json 2>&1)"; then
  echo "Could not list the secrets of ${GATEWAY_APP}: not touching the master key. ${LISTING}" >&2
  exit 1
fi
if ! HAS_MASTER="$(printf '%s' "$LISTING" | python3 -c 'import json,sys; print(any((s.get("Name") or s.get("name")) == "LITELLM_MASTER_KEY" for s in json.load(sys.stdin)))')"; then
  echo "Could not read the secret listing of ${GATEWAY_APP}: not touching the master key." >&2
  exit 1
fi
if [ "$HAS_MASTER" = "True" ]; then
  echo "== LITELLM_MASTER_KEY already set on ${GATEWAY_APP}: keeping it"
else
  # secrets staged but not yet deployed may not be listed: never replace a key without asking
  ANSWER=""
  read -r -p "No LITELLM_MASTER_KEY is visible on ${GATEWAY_APP}. Generate a NEW one? [y/N] " ANSWER || true
  [ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ] || echo "== not generating a master key (the gateway will not start without one)"
  if [ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ]; then NEW_MASTER="sk-$(openssl rand -hex 32)"; fi
fi

echo "== setting secrets on ${GATEWAY_APP} (staged: no deploy yet)"
{
  [ -n "$NEW_MASTER" ] && echo "LITELLM_MASTER_KEY=${NEW_MASTER}"
  [ -n "$MISTRAL_API_KEY" ] && echo "MISTRAL_API_KEY=${MISTRAL_API_KEY}"
  if [ -n "$AZURE_API_KEY" ]; then echo "AZURE_API_KEY=${AZURE_API_KEY}"; echo "AZURE_API_BASE=${AZURE_API_BASE}"; fi
  if [ -n "$AWS_ACCESS_KEY_ID" ]; then
    echo "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}"; echo "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
    echo "AWS_REGION_NAME=eu-central-1"
  fi
} | fly secrets import --stage --app "$GATEWAY_APP"

if [ -n "$NEW_MASTER" ]; then
  echo
  echo "GATEWAY MASTER KEY (shown once, not stored anywhere else): ${NEW_MASTER}"
  echo "Save it in your password manager now. You need it only to create or rotate keys."
  echo
fi
echo "== done. Tell Claude Code which providers you set: it enables the verified models in the"
echo "   catalogue, deploys the gateway and switches the pilot over (runbook steps 8-12)."
