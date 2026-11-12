#!/usr/bin/env bash
# Supabase pilot: prepare the database and set the Fly.io secrets (runbook: docs/platform/runbooks/supabase-pilot.md, steps 2-3).
# Run it yourself in a terminal: it asks for the secrets silently, nothing is echoed, logged or committed.
# Prerequisites: `brew install flyctl uv`, `fly auth login`, `fly apps create mgr-ibm-bomagent` (once).
set -euo pipefail
cd "$(dirname "$0")/.."

REF="wdjhfugsduoymelipimq"
POOLER="aws-0-eu-west-1.pooler.supabase.com"
APP="mgr-ibm-bomagent"
VAULT="${HOME}/.mgr-ibm-pilot-secrets.env" # chmod 600; copy into your password manager, then you may delete it

read -r -s -p "Supabase database password (Connect -> Reset database password): " DBPASS; echo
read -r -s -p "Supabase Storage S3 access key ID (Storage -> S3 -> New access key): " S3ID; echo
read -r -s -p "Supabase Storage S3 secret access key: " S3SECRET; echo

if [ ! -f "$VAULT" ]; then
  umask 077
  {
    echo "BOMAGENT_MIGRATOR_PASSWORD=$(openssl rand -hex 24)"
    echo "BOMAGENT_APP_PASSWORD=$(openssl rand -hex 24)"
    echo "BOMAGENT_PLATFORM_PASSWORD=$(openssl rand -hex 24)"
  } > "$VAULT"
  echo "Generated role passwords -> $VAULT (save them in your password manager)"
fi
set -a; . "$VAULT"; set +a

echo "== 1/3 database preparation (creates database bomagent, 3 roles, pgvector)"
uv sync --all-packages --quiet
BOMAGENT_ADMIN_DATABASE_URL="postgresql+psycopg://postgres.${REF}:${DBPASS}@${POOLER}:5432/postgres?sslmode=require" \
BOMAGENT_DATABASE_NAME=bomagent \
  uv run python -m bomagent_allinone bootstrap

echo "== 2/3 Fly.io secrets (app ${APP})"
fly secrets import --app "$APP" <<EOF
BOMAGENT_DATABASE_PASSWORD=${BOMAGENT_APP_PASSWORD}
BOMAGENT_PLATFORM_DATABASE_PASSWORD=${BOMAGENT_PLATFORM_PASSWORD}
BOMAGENT_MIGRATOR_DATABASE_URL=postgresql+psycopg://bomagent_migrator.${REF}:${BOMAGENT_MIGRATOR_PASSWORD}@${POOLER}:5432/bomagent?sslmode=require
AWS_ACCESS_KEY_ID=${S3ID}
AWS_SECRET_ACCESS_KEY=${S3SECRET}
EOF

echo "== 3/3 done. Next: fly deploy . --config deploy/supabase/fly.toml --dockerfile deploy/docker/allinone.Dockerfile --ha=false"
