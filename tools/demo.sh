#!/usr/bin/env bash
# Local demo without Docker and without LLM keys (macOS or Linux).
# Starts the all-in-one API (fake LLM, in-memory queues and storage) with demo data,
# then the web app on http://localhost:5173. Ctrl-C stops both; the demo database is dropped.
#
# Needs: PostgreSQL 16+ with pgvector running locally, uv, Node 22 + pnpm.
# Admin URL defaults to the Homebrew/Postgres.app setup (your macOS user, no password);
# override with BOMAGENT_DEV_ADMIN_URL=postgresql+psycopg://user:pass@localhost:5432/postgres
set -euo pipefail
cd "$(dirname "$0")/.."

for tool in uv pnpm node; do
  command -v "$tool" >/dev/null || { echo "demo: '$tool' not found - see docs/HANDOFF.md (Local demo)"; exit 1; }
done
export BOMAGENT_DEV_ADMIN_URL="${BOMAGENT_DEV_ADMIN_URL:-postgresql+psycopg://${USER}@localhost:5432/postgres}"
API_PORT="${BOMAGENT_PORT:-8000}"
WEB_PORT="${BOMAGENT_WEB_PORT:-5173}"

uv sync --all-packages --quiet
pnpm install --frozen-lockfile --silent

log="$(mktemp -t bomagent-demo.XXXXXX)"
uv run python tools/devstack.py --port "$API_PORT" --seed >"$log" 2>&1 &
api_pid=$!
cleanup() { kill "$api_pid" 2>/dev/null || true; wait "$api_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "demo: starting the API and creating demo data (log: $log) ..."
for _ in $(seq 1 180); do
  if grep -q "demo data ready" "$log"; then break; fi
  if ! kill -0 "$api_pid" 2>/dev/null; then echo "demo: API failed to start:"; tail -30 "$log"; exit 1; fi
  sleep 1
done
grep -q "demo data ready" "$log" || { echo "demo: timed out:"; tail -30 "$log"; exit 1; }

cat <<MSG

  BOM Agent demo:  http://localhost:${WEB_PORT}
  Sign in with:    anna@medtech-demo.example  (any name; local test identity provider)
  Demo data:       organisation "MedTech Demo", 3 KiCad projects, 4 finished runs (A and B)
  Stop:            Ctrl-C

MSG
BOMAGENT_API_URL="http://127.0.0.1:${API_PORT}" pnpm --filter @bomagent/web exec vite --port "$WEB_PORT" --strictPort
