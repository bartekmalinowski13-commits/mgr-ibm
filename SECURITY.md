# Security policy

BOM Agent processes design files of medical-device companies, so security reports are taken
seriously. The platform's own security model is described in
[`docs/platform/SECURITY.md`](docs/platform/SECURITY.md).

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability.

Use GitHub's private reporting: the **Security** tab of this repository, then
**Report a vulnerability**. Include what you found, how to reproduce it, the affected version or
commit, and the impact you expect. Do not include real customer data.

What to expect:

- acknowledgement within 5 working days;
- an assessment and a plan within 15 working days;
- a fix or mitigation, and credit if you want it, once the issue is resolved.

## Scope

In scope: this repository's code and infrastructure definitions, in particular tenant isolation
(Postgres RLS), authentication and authorization, the file parsers and their sandbox, the LLM
gateway and its EU-only guard, and the audit log.

Out of scope: social engineering, denial of service by volume, findings that need a compromised
administrator account, and third-party services (report those to the vendor).

## Supported versions

The `main` branch is the only supported version until the first release.

## Handling

Fixes for confirmed vulnerabilities are developed privately where needed, released together with
an advisory, and tracked in `docs/STATUS.md` once public.
