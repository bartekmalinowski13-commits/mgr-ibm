#!/usr/bin/env bash
# LLM gateway of the Supabase pilot: create the Fly app and set the provider secrets
# (runbook: docs/platform/runbooks/llm-gateway-pilot.md, steps 4 and 6; the owner guide in
# Polish: docs/owner-guides/KLUCZE_LLM_KROK_PO_KROKU.md).
# Run it yourself in a terminal. Every key is asked silently (nothing is echoed or logged);
# press Enter to skip a provider you do not have yet. Re-run it any time to add providers.
# It does NOT deploy and does NOT touch the main app: Claude Code does that after the
# models are enabled in the catalogue (step 8) and the gateway image is built.
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
GATEWAY_APP="mgr-ibm-llm-gateway"
MAIN_APP="mgr-ibm-bomagent"
VAULT="${HOME}/.mgr-ibm-llm-secrets.env" # chmod 600; copy into your password manager

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

if [ ! -f "$VAULT" ]; then
  umask 077
  echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)" > "$VAULT"
  echo "Generated the gateway master key -> $VAULT (save it in your password manager)"
fi
set -a; . "$VAULT"; set +a

if ! fly apps list --json | grep -q "\"Name\": *\"${GATEWAY_APP}\""; then
  ORG="$(fly apps list --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((a.get("Organization",{}).get("Slug","personal") for a in d if a["Name"]=="'"${MAIN_APP}"'"), "personal"))')"
  echo "== creating Fly app ${GATEWAY_APP} in organisation ${ORG} (same as ${MAIN_APP})"
  fly apps create "$GATEWAY_APP" --org "$ORG"
fi

echo "== setting secrets on ${GATEWAY_APP} (staged: no deploy yet)"
{
  echo "LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}"
  [ -n "$MISTRAL_API_KEY" ] && echo "MISTRAL_API_KEY=${MISTRAL_API_KEY}"
  if [ -n "$AZURE_API_KEY" ]; then echo "AZURE_API_KEY=${AZURE_API_KEY}"; echo "AZURE_API_BASE=${AZURE_API_BASE}"; fi
  if [ -n "$AWS_ACCESS_KEY_ID" ]; then
    echo "AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}"; echo "AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
    echo "AWS_REGION_NAME=eu-central-1"
  fi
} | fly secrets import --stage --app "$GATEWAY_APP"

echo "== done. Tell Claude Code which providers you set: it enables the verified models in the"
echo "   catalogue, deploys the gateway and switches the pilot over (runbook steps 8-12)."
