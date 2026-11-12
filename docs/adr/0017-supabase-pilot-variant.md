# ADR-0017: A second, lightweight deployment variant on Supabase (EU) for pilots

Status: Proposed · 2026-11-12 (requested by the owner; pending acceptance – see `docs/DECISIONS_LOG.md`)

## Context
The production target is AWS in the EU with several accounts (ADR-0002, ADR-0003, ADR-0005). Setting
that up takes time and has fixed monthly costs. The owner wants, in addition, a quick and cheap way
to put the app in front of testers and the thesis supervisor, while the AWS path stays the primary
one (and the one the thesis describes). The code already isolates tenants in PostgreSQL (RLS,
ADR-0004), talks to object storage through the S3 API and verifies OIDC JWTs through JWKS, so most
of it does not depend on AWS-specific services.

## Decision
- A **second deployment variant**, "Supabase pilot", next to AWS. AWS stays primary; nothing in the
  AWS path changes because of this variant.
- **Supabase project in the EU (Frankfurt)** provides PostgreSQL with pgvector (own database
  `bomagent`, the same migrations and roles as in AWS, ADR-0016), Auth (e-mail + password; access
  tokens verified by the API through the project's JWKS, asymmetric keys only) and Storage through
  its S3-compatible endpoint.
- **One container** (`services/all-in-one`: API + ingest worker + agent worker + kb-indexer + the
  built SPA) on an EU container host (configuration for Fly.io, region `fra`; the image is
  host-agnostic). Queues use a PostgreSQL-backed queue with RLS instead of SQS.
- Parsing keeps the resource-limited sandbox. LLM calls go only through the LLM gateway settings;
  without an EU model provider configured, the deterministic fake model is used (no real BOMs).
- **Not available** in this variant: SSO per organisation (Cognito federation), WAF, the AWS
  audit/backup/observability stacks, Bedrock. Supabase's Data API must not expose our schemas:
  the migrations revoke our schemas from Supabase's `anon`/`authenticated`/`service_role` roles.
- Use: pilots, demos and tests with **non-confidential data** until the owner has checked the
  providers' data processing terms (DPA, EU residency, sub-processors).

## Consequences
A shareable app in hours instead of days, with low fixed cost. Cost: two deployment targets to keep
working (the all-in-one service and the Postgres queue must be tested in CI like the AWS services);
weaker guardrails than the AWS path (no SCPs, no WAF, a single process). Supabase and the container
host are additional data processors - an explicit owner decision before any customer data.

## Alternatives considered
Only AWS (no quick option - remains the primary path); running everything on one VM (more
operations work, no managed auth); a different all-in-one PaaS for the database (Supabase gives
PostgreSQL with pgvector, auth and S3-compatible storage in one EU project).
