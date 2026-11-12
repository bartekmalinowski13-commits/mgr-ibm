# ADR-0005: Identity: OIDC, Amazon Cognito, SSO per organization

Status: Accepted · 2026-11-09

## Context
B2B customers expect SSO (SAML/OIDC), MFA and roles.

## Decision
Cognito in `eu-central-1` with SAML 2.0 / OIDC federation configured per organization; the application depends only on the OIDC standard (JWT). RBAC: owner, admin, engineer, reviewer, viewer; policies in the `authz` module in the Cedar style. API keys per organization. SCIM – a separate ADR at the first Enterprise customer.

## Consequences
Identity data in the EU, a managed service. Limitation: Cognito has no SCIM – hence the dependency only on OIDC, so that a move to Keycloak is possible.

## Alternatives considered
Self-hosted Keycloak (full control, but operations and security updates on our side); Auth0/Clerk/WorkOS (great DX, but an additional data sub-processor and a residency question).
