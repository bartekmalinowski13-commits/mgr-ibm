# M4 – SaaS platform: backend (plan and status)

Sources: ROADMAP M4, ADR-0004/0005/0011/0015, SECURITY.md, TESTING.md.

## Brainstorming – questions and answers
| Question | Decision | Rationale |
|---|---|---|
| Where do user roles come from? | from the database (`tenancy.memberships`), not from the token | a role changes without re-login; the IdP token does not know BOM Agent organizations |
| How to find a user's organizations at login without bypassing RLS? | `app.user_sub` + the `member_self`/`member_tenants` policies (SELECT of own memberships only) | no roles with BYPASSRLS (CLAUDE.md) |
| Who creates a tenant? | the `bomagent_platform` role (onboarding), audit in the new tenant | the application role cannot create tenants |
| Local IdP | RS256 mock with an ephemeral key, local/test only | ADR-0005: the application depends only on OIDC |
| BOM editing | a new immutable version + `user` provenance + MPN correction as tenant knowledge | ISO 13485 traceability, ADR-0008 |
| Parsing uploaded files | only in the ingest-worker (sandbox), the API only stores and enqueues | ADR-0009 |

## Status
1. Migration 0003 + isolation tests – ✅
2. API: auth/RBAC/organizations/projects/upload/runs/SSE/BOM/editing/export/audit, OpenAPI 3.1, contract (Schemathesis) – ✅
3. Workers write to the database (run status, BOM versions, parsing result) – ✅
4. TS client from OpenAPI – next step
5. To do later: member invitations, organization API keys, limits/metering, per-organization SSO configuration (form → Cognito), rate limiting.

## Acceptance criteria
Contract, integration and isolation tests green; an audit event for every mutation (checked in `test_api_flow`).
