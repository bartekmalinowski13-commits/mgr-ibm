#!/usr/bin/env bash
# Runs once on an empty data directory (docker-entrypoint-initdb.d).
# Creates platform roles, the application database and the Langfuse database.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
$(cat /bootstrap/bootstrap.sql)
ALTER ROLE bomagent_migrator WITH PASSWORD '${BOMAGENT_MIGRATOR_PASSWORD}';
ALTER ROLE bomagent_app WITH PASSWORD '${BOMAGENT_APP_PASSWORD}';
ALTER ROLE bomagent_platform WITH PASSWORD '${BOMAGENT_PLATFORM_PASSWORD}';
CREATE DATABASE bomagent OWNER bomagent_migrator;
CREATE DATABASE langfuse;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname bomagent <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE bomagent TO bomagent_app, bomagent_platform;
SQL
