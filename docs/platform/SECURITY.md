# Security, privacy, compliance

Goal: a level ready for an audit at a medtech customer. Target **OWASP ASVS level 2** for the application, controls ready for ISO/IEC 27001 / SOC 2, support for the traceability needs of customers operating under ISO 13485.

## Regulatory position (to be confirmed with an advisor)
The platform is a design-support (engineering) tool, not software intended for diagnosis or therapy – most likely it **is not a medical device** within the meaning of MDR 2017/745. Customers do, however, use it in a design process covered by ISO 13485, so we provide: an audit log, provenance of every BOM item, versioning, evidence export. Any tool validation on the customer's side (ISO 13485 §4.1.6) – validation documentation as a future product.

## GDPR
- Processing and storage exclusively in the EU (ADR-0002, ADR-0006).
- Role: processor for customer data; DPA agreement; public list of sub-processors (AWS; Microsoft – Azure OpenAI; Mistral; – each with processing in the EU).
- Minimization: personal data only of users (name, e-mail, access logs). Design files are the customer's trade secret – treated as data of the highest confidentiality.
- Retention configurable per organization; export and permanent deletion of the organization's data (offboarding) with confirmation in the audit log.

## Threat model (summary, STRIDE)
| Threat | Control |
|---|---|
| Access to another organization's data | RLS + tenant context + S3 ABAC + isolation tests in CI (block merge) |
| Malicious file (zip bomb, XXE, parser exploit) | malware scan, size/time limits, parser in an isolated task without network, non-root, read-only FS, safe XML parsers (defusedxml) |
| Prompt injection from files/datasheets | document content always as data (separated from instructions), agent tools with minimal permissions and only within the tenant context, LLM output validated against a schema, the agent does not execute code or make network requests |
| Data leak to a non-EU LLM provider | LLM Gateway only, egress allowlist, model catalogue with a residency attribute, configuration tests |
| Account takeover | SSO, MFA for admins, short-lived tokens, refresh with rotation, login anomaly detection (Cognito advanced security) |
| Cost abuse (LLM) | budgets and limits per tenant and per run, rate limiting |
| Dependency / image tampering | lockfile, Renovate/Dependabot, Trivy, SBOM (Syft), image signing (cosign), GitHub actions pinned to SHA |
| Secret leakage | Secrets Manager, gitleaks in CI and pre-commit, no secrets in logs (filters) |
| Audit log tampering | append-only + hash chain + S3 Object Lock in a separate log-archive account |

## Infrastructure
WAF (AWS Managed Rules sets + rate limiting) on CloudFront; TLS 1.2+ everywhere; encryption at rest with KMS (Aurora, S3, SQS, logs); databases in private subnets; VPC endpoints; GuardDuty (including Malware Protection for S3 and Runtime Monitoring for ECS), Security Hub (AWS FSBP, CIS), AWS Config, IAM Access Analyzer, organization CloudTrail; SCPs: EU regions only, no disabling of CloudTrail/GuardDuty, no public buckets.

## Application
Input validation (Pydantic), CSP and security headers, CSRF protection for cookie sessions, CORS only for own domains, request limits per tenant and API key, idempotency, no file content or prompts in application logs (in Langfuse only within the tenant space and with retention), DAST scan (OWASP ZAP baseline) on staging.

## Processes
Security review of every migration that changes RLS policies; quarterly permission review; incident response plan (runbook in `docs/runbooks/`); penetration tests before the first production customer.
