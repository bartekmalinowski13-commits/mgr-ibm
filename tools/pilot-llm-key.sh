#!/usr/bin/env bash
# Create (or rotate) the LiteLLM virtual key the pilot app uses, and hand it straight to Fly.
# Runbook: docs/platform/runbooks/key-rotation.md (and llm-gateway-pilot.md step 10).
#
# Usage:
#   tools/pilot-llm-key.sh [--alias NAME] [--budget AMOUNT] [--duration 75d] [--delete-alias OLD]
#   tools/pilot-llm-key.sh --delete-only --delete-alias OLD      (retire a key, create nothing)
#
# Run it yourself in a terminal. It asks for the gateway master key silently (get it from your
# password manager), opens a private tunnel to the gateway on a free localhost port, creates a
# key limited to the models the gateway serves with a budget and an expiry, and stores the new key
# as the Fly secret BOMAGENT_LLM_GATEWAY_KEY of the main app. Neither key is printed, written to a
# file or passed on a command line (curl reads its Authorization header from stdin, `fly secrets
# import` reads the new key from stdin). Setting the secret restarts the app. Rotation: run it
# with a new --alias, check /readyz, then run with --delete-only --delete-alias <old alias>.
set -euo pipefail
case $- in *x*) echo "Refusing to run with tracing (set -x): it would print the keys." >&2; exit 1 ;; esac
export PATH="/opt/homebrew/bin:$PATH"
GATEWAY_APP="${GATEWAY_APP:-mgr-ibm-llm-gateway}"
MAIN_APP="${MAIN_APP:-mgr-ibm-bomagent}"
ALIAS="bomagent-pilot-$(date +%Y%m%d)"
BUDGET="20"
DURATION="75d"
DELETE_ALIAS=""
DELETE_ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --alias) ALIAS="${2:?--alias needs a value}"; shift 2 ;;
    --budget) BUDGET="${2:?--budget needs a value}"; shift 2 ;;
    --duration) DURATION="${2:?--duration needs a value}"; shift 2 ;;
    --delete-alias) DELETE_ALIAS="${2:?--delete-alias needs a value}"; shift 2 ;;
    --delete-only) DELETE_ONLY=1; shift ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done
[ -z "$DELETE_ONLY" ] || [ -n "$DELETE_ALIAS" ] || { echo "--delete-only needs --delete-alias" >&2; exit 2; }
[[ "$BUDGET" =~ ^(0|[1-9][0-9]*)(\.[0-9]+)?$ ]] || { echo "--budget must be a plain number" >&2; exit 2; }
[[ "$DURATION" =~ ^[1-9][0-9]*[smhd]$ ]] || { echo "--duration looks like 75d, 12h, 30m" >&2; exit 2; }
if [ -z "$DELETE_ONLY" ] && [ "$DELETE_ALIAS" = "$ALIAS" ]; then
  echo "--delete-alias must differ from --alias (it would delete the key just created)" >&2; exit 2
fi

command -v fly >/dev/null || { echo "flyctl not found: brew install flyctl && fly auth login" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl not found" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }

MASTER=""
read -r -s -p "Gateway master key (from your password manager): " MASTER || true
echo >&2
[ -n "$MASTER" ] || { echo "No master key given - nothing to do." >&2; exit 1; }
[[ "$MASTER" =~ ^[A-Za-z0-9._~-]+$ ]] || { echo "The master key has unexpected characters." >&2; exit 1; }

PORT="${PROXY_PORT:-$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')}"
WORK="$(mktemp -d)"; chmod 700 "$WORK"
PROXY=""
cleanup() { [ -z "$PROXY" ] || kill "$PROXY" 2>/dev/null || true; rm -rf "$WORK"; MASTER=""; }
trap cleanup EXIT
fly proxy "${PORT}:4000" -a "$GATEWAY_APP" --bind-addr 127.0.0.1 >/dev/null 2>&1 &
PROXY=$!

api() { # api METHOD PATH [body-file]: the master key goes to curl on stdin, never on argv
  local args=(-sS --fail-with-body -X "$1" -K -)
  [ -z "${3:-}" ] || args+=(-H "Content-Type: application/json" --data-binary "@$3")
  printf 'header = "Authorization: Bearer %s"\n' "$MASTER" | curl "${args[@]}" "http://127.0.0.1:${PORT}$2"
}

error_text() { # the message of a LiteLLM error reply (never a key)
  python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    err = json.loads(raw).get("error") or {}
    print(err.get("message") if isinstance(err, dict) else err)
except Exception:
    print(raw[:200])'
}

json_body() { # json_body name=string name:=json name[]=item ... : a flat JSON object
python3 - "$@" <<'PY'
import json, sys
out = {}
for pair in sys.argv[1:]:
    name, _, value = pair.partition("=")
    if name.endswith(":"):
        out[name[:-1]] = json.loads(value)
    elif name.endswith("[]"):
        out.setdefault(name[:-2], []).append(value)
    else:
        out[name] = value
print(json.dumps(out))
PY
}

sleep "${PROXY_SETTLE:-0.3}"
tries="${PROXY_WAIT_TRIES:-30}"
while :; do
  kill -0 "$PROXY" 2>/dev/null || { echo "The tunnel to ${GATEWAY_APP} exited (not logged in to Fly?)." >&2; exit 1; }
  curl -sf "http://127.0.0.1:${PORT}/health/liveliness" >/dev/null 2>&1 && break
  tries=$((tries - 1)); [ "$tries" -gt 0 ] || { echo "The gateway did not answer through the tunnel." >&2; exit 1; }
  sleep 1
done

if [ -z "$DELETE_ONLY" ]; then
  MODELS="$(api GET /v1/models | python3 -c 'import json,sys; print(json.dumps([m["id"] for m in json.load(sys.stdin)["data"]]))')"
  [ "$MODELS" != "[]" ] || { echo "The gateway serves no models: enable some in the catalogue first." >&2; exit 1; }
  json_body "key_alias=${ALIAS}" "models:=${MODELS}" "max_budget:=${BUDGET}" "duration=${DURATION}" > "$WORK/body.json"
  if ! RESP="$(api POST /key/generate "$WORK/body.json")"; then
    echo "The gateway refused the request: $(printf '%s' "$RESP" | error_text)" >&2; exit 1
  fi
  NEWKEY="$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')" \
    || { echo "The gateway reply had no key." >&2; exit 1; }
  if ! printf 'BOMAGENT_LLM_GATEWAY_KEY=%s\n' "$NEWKEY" | fly secrets import --app "$MAIN_APP" >/dev/null; then
    echo "The key '${ALIAS}' exists in the gateway but could not be stored as a Fly secret." >&2
    echo "Retire it:  tools/pilot-llm-key.sh --delete-only --delete-alias ${ALIAS}" >&2
    exit 1
  fi
  NEWKEY=""; RESP=""
  echo "Virtual key '${ALIAS}' (budget ${BUDGET}, ${DURATION}) is now the secret of ${MAIN_APP}; the app restarts." >&2
  echo "Check: curl -s https://${MAIN_APP}.fly.dev/readyz  (\"llm\":\"gateway\")" >&2
  echo "Note: the key is limited to the models enabled today; rotate it after enabling more." >&2
fi

if [ -n "$DELETE_ALIAS" ]; then
  json_body "key_aliases[]=${DELETE_ALIAS}" > "$WORK/delete.json"
  api POST /key/delete "$WORK/delete.json" >/dev/null
  echo "Old key '${DELETE_ALIAS}' deleted." >&2
fi
