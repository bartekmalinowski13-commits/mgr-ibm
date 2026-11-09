#!/usr/bin/env bash
# Runs once on an empty data directory (docker-entrypoint-initdb.d).
# Creates platform roles, the application database and the Langfuse database.
# Passwords are passed as psql variables and quoted by psql (:'var'), never pasted into SQL.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v migrator_pw="$BOMAGENT_MIGRATOR_PASSWORD" \
  -v app_pw="$BOMAGENT_APP_PASSWORD" \
  -v platform_pw="$BOMAGENT_PLATFORM_PASSWORD" <<'SQL'
\i /bootstrap/bootstrap.sql
ALTER ROLE bomagent_migrator WITH PASSWORD :'migrator_pw';
ALTER ROLE bomagent_app WITH PASSWORD :'app_pw';
ALTER ROLE bomagent_platform WITH PASSWORD :'platform_pw';
CREATE DATABASE bomagent OWNER bomagent_migrator;
CREATE DATABASE langfuse;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname bomagent <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE bomagent TO bomagent_app, bomagent_platform;
SQL
