# ADR-0004: Multi-tenancy: pooled model with Postgres RLS, silo for the Enterprise plan

Status: Accepted · 2026-11-09

## Context
Many organizations, strong isolation required, simple onboarding of new customers.

## Decision
A shared database with a `tenant_id` column and Row-Level Security on every tenant table; `SET LOCAL app.tenant_id` in every transaction; application role without BYPASSRLS. S3: per-tenant prefix + ABAC. Enterprise plan: a dedicated Aurora cluster and KMS key, connection routing by `tenant_id`. A mandatory isolation test suite in CI.

## Consequences
Cheap onboarding (a database record, not new infrastructure), defence in depth. Risk: an error in an RLS policy – mitigated by isolation tests and review of every migration.

## Alternatives considered
Schema per tenant (migration problems with hundreds of tenants); database per tenant for everyone (cost).
