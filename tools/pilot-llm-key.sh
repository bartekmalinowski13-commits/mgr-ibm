#!/usr/bin/env bash
# Create (or rotate) the LiteLLM virtual key the pilot app uses, and hand it straight to Fly.
# Runbook: docs/platform/runbooks/key-rotation.md (and llm-gateway-pilot.md step 10).
#
#   tools/pilot-llm-key.sh [--alias NAME] [--budget EUR] [--duration 90d] [--delete-alias OLD]
#   tools/pilot-llm-key.sh --delete-only --delete-alias OLD      (retire a key, create nothing)
#
# Run it yourself in a terminal. It asks for the gateway master key silently (get it from your
# password manager), opens a private tunnel to the gateway, creates a key limited to the models
# the gateway serves with a budget and an expiry, and stores the new key as the Fly secret
# BOMAGENT_LLM_GATEWAY_KEY of the main app. Neither key is printed, written to a file or passed
# on a command line (curl reads its Authorization header from stdin, `fly secrets import` reads
# the new key from stdin). Setting the secret restarts the app. Rotation: run it with a new
# --alias, check /readyz, then run with --delete-only --delete-alias <old alias> to retire it.
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
GATEWAY_APP="${GATEWAY_APP:-mgr-ibm-llm-gateway}"
MAIN_APP="${MAIN_APP:-mgr-ibm-bomagent}"
PORT="${PROXY_PORT:-4000}"
ALIAS="bomagent-pilot-$(date +%Y%m%d)"
BUDGET="20"
DURATION="90d"
DELETE_ALIAS=""
DELETE_ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --alias) ALIAS="${2:?--alias needs a value}"; shift 2 ;;
    --budget) BUDGET="${2:?--budget needs a value}"; shift 2 ;;
    --duration) DURATION="${2:?--duration needs a value}"; shift 2 ;;
    --delete-alias) DELETE_ALIAS="${2:?--delete-alias needs a value}"; shift 2 ;;
    --delete-only) DELETE_ONLY=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done
[ -z "$DELETE_ONLY" ] || [ -n "$DELETE_ALIAS" ] || { echo "--delete-only needs --delete-alias" >&2; exit 2; }
case "$BUDGET" in ''|*[!0-9.]*) echo "--budget must be a number (EUR)" >&2; exit 2 ;; esac

command -v fly >/dev/null || { echo "flyctl not found: brew install flyctl && fly auth login" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl not found" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }

read -r -s -p "Gateway master key (from your password manager): " MASTER; echo >&2
[ -n "$MASTER" ] || { echo "No master key given - nothing to do." >&2; exit 1; }

WORK="$(mktemp -d)"; chmod 700 "$WORK"
fly proxy "${PORT}:4000" -a "$GATEWAY_APP" >/dev/null 2>&1 &
PROXY=$!
cleanup() { kill "$PROXY" 2>/dev/null || true; rm -rf "$WORK"; unset MASTER; }
trap cleanup EXIT

api() { # api METHOD PATH [body-file]: the master key goes to curl on stdin, never on argv
  local method="$1" path="$2" body="${3:-}" args=(-sS --fail-with-body -X "$1" -K -)
  [ -n "$body" ] && args+=(-H "Content-Type: application/json" --data-binary "@${body}")
  printf 'header = "Authorization: Bearer %s"\n' "$MASTER" | curl "${args[@]}" "http://localhost:${PORT}${path}"
}

tries="${PROXY_WAIT_TRIES:-30}"
until curl -sf "http://localhost:${PORT}/health/liveliness" >/dev/null 2>&1; do
  tries=$((tries - 1)); [ "$tries" -gt 0 ] || { echo "The gateway did not answer through the tunnel." >&2; exit 1; }
  sleep 1
done

json_body() { # json_body key=string key:=json ... : a flat JSON object
python3 - "$@" <<'PY'
import json, sys
out = {}
for pair in sys.argv[1:]:
    if ":=" in pair.split("=", 1)[0] + "=" and pair.partition(":=")[0].isidentifier():
        key, _, value = pair.partition(":=")
        out[key] = json.loads(value)
    else:
        key, _, value = pair.partition("=")
        out[key] = value
print(json.dumps(out))
PY
}

if [ -z "$DELETE_ONLY" ]; then
  MODELS="$(api GET /v1/models | python3 -c 'import json,sys; print(json.dumps([m["id"] for m in json.load(sys.stdin)["data"]]))')"
  [ "$MODELS" != "[]" ] || { echo "The gateway serves no models: enable some in the catalogue first." >&2; exit 1; }
  json_body "key_alias=${ALIAS}" "models:=${MODELS}" "max_budget:=${BUDGET}" "duration=${DURATION}" > "$WORK/body.json"
  api POST /key/generate "$WORK/body.json" \
    | python3 -c 'import json,sys; print("BOMAGENT_LLM_GATEWAY_KEY=" + json.load(sys.stdin)["key"])' \
    | fly secrets import --app "$MAIN_APP" >/dev/null
  echo "Virtual key '${ALIAS}' (budget ${BUDGET} EUR, ${DURATION}) is now the secret of ${MAIN_APP}; the app restarts." >&2
  echo "Check: curl -s https://${MAIN_APP}.fly.dev/readyz  (\"llm\":\"gateway\")" >&2
fi

if [ -n "$DELETE_ALIAS" ]; then
  json_body "key_aliases:=[\"${DELETE_ALIAS}\"]" > "$WORK/delete.json"
  api POST /key/delete "$WORK/delete.json" >/dev/null
  echo "Old key '${DELETE_ALIAS}' deleted." >&2
fi
