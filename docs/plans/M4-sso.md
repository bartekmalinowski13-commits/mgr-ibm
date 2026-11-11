# SSO per organisation (ADR-0005)

Status: implemented (code, tests, infrastructure); needs a deployed Cognito pool to use
with a real identity provider.

## Flow

1. **Domain.** An owner/admin adds an e-mail domain and publishes the DNS TXT record
   `_bomagent-verify.<domain>` = `bomagent-verification=<token>`; verifying checks it over
   DNS. A verified domain belongs to one organisation (unique index).
2. **Connection.** One SAML 2.0 (metadata URL) or OIDC (issuer, client id, secret)
   identity provider per organisation, created in the Cognito user pool as
   `org-<organisation id prefix>` and enabled on the SPA app client. The OIDC client
   secret is passed to Cognito only. The settings page shows the values to register at
   the customer's identity provider (reply/ACS URL, entity id).
3. **Sign-in.** The sign-in page asks for the e-mail; `GET /v1/sso/discover` returns the
   provider for a verified domain with an active connection and the SPA adds
   `identity_provider=<name>` to the Cognito authorize URL.
4. **Membership.** Cognito's ID token carries `identities[0].providerName`; a user who
   came through the organisation's provider with an e-mail in one of its verified domains
   becomes a member with the connection's default role (never owner/admin), audited as
   `member.joined_via_sso`.
5. **Enforcement.** Optional: members with an e-mail in a verified domain must sign in
   through the provider (`403 sso-required` otherwise). Owners are exempt (break-glass
   when the identity provider fails). Removing the last verified domain switches it off.

## Isolation

Tables `tenancy.sso_connections` and `tenancy.sso_domains` (migration 0010) have forced
RLS. The two lookups that run before any tenant context (discovery by domain, membership
by provider) use dedicated policies keyed by `app.sso_domain` / `app.sso_provider`, like
the API-key lookup - isolation tests in `tests/isolation/test_platform_isolation.py`.

## Local preview and tests

Locally the API uses an in-memory identity broker and a static DNS resolver;
`POST /v1/sso/dev/dns` (local/test only) sets a TXT record and the dev token endpoint can
simulate a federated sign-in. E2E: `apps/web/e2e/sso.spec.ts`.

## Not in this step

SCIM provisioning (ADR-0005: separate ADR with the first Enterprise customer), group to
role mapping, enforcing MFA for owners/admins (Cognito MFA is optional at pool level).
