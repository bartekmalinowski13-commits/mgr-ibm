# ADR-0018: Deployment tiers - Standard (Fly + Supabase) and Enterprise (AWS)

Status: Proposed · 2026-11-16 (audit ARCH-01; pending acceptance - see `docs/DECISIONS_LOG.md`)

## Context
Two deployment paths exist. AWS (ADR-0002, 0003, 0005): multi-account, ECS Fargate, Cognito, WAF,
Object Lock - primary in the architecture and the thesis, never deployed. Supabase + Fly.io
(ADR-0017, "Proposed"): one container, PostgreSQL queue, Supabase Auth - live as the pilot, with
weaker guardrails. The pilot is where real users will form their opinion; every change has to be
tested against both paths. The independent audit (`docs/audit/FABLE_AUDIT_EN.md`, ARCH-01/ARCH-02)
asks for an explicit decision instead of two paths that drift apart.

## Decision
- Two named **tiers** of one product, one code base, one composition root (`bomagent_allinone`
  composes the services; the AWS services use the same packages):
  - **Standard** - Fly.io (`fra`) + Supabase (EU): pooled tenants, RLS, shared infrastructure.
    First-class, hardened (parser isolation, per-IP limits, observability, backups, MFA), and the
    tier used for the first paying pilot customers.
  - **Enterprise** - AWS multi-account: silo option per tenant, SSO per organisation (Cognito),
    WAF, Object Lock anchors, VPC-isolated parsing. Roadmap: deployed dev -> staging -> prod via the
    pipeline, by a human (CLAUDE.md rule 6).
- Features that exist in only one tier are listed in `docs/platform/ARCHITECTURE.md` ("As built"
  table, audit ARCH-09) with the evidence path; a feature may not be advertised for a tier that
  lacks it (SSO per organisation: Enterprise only).
- Every tier runs the same API contract tests and the same end-to-end suite in CI; a change that
  cannot be tested on both is split into a shared part and a tier-specific part.
- ADR-0017 is accepted together with this ADR (its "pilot only, non-confidential data" limits are
  lifted per tier as the hardening items of the audit land, not by default).

## Consequences
One decision to explain to customers and examiners; the thesis keeps the AWS narrative while the
product ships on Standard. Cost: two targets to maintain; the all-in-one image must stay close to
the multi-service images (process groups on Fly, audit ARCH-02, keep that gap small).

## Alternatives considered
Deploy AWS dev now and retire the pilot after the defence (cleaner story, but the live pilot would
stop and the AWS path is not ready for users); keep both paths unspecified (status quo: drift,
double testing without a rule).
