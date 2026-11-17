# Sub-processors of BOM Agent

Status: **draft prepared from the repository (ADRs, runbooks). Not a legal statement.** Every fact
about a contract, a region or a data-processing term that is not written in the repository is
marked **to be confirmed by the owner**. Nothing here has been verified with the vendors.

BOM Agent acts as a processor of customer data (`docs/platform/SECURITY.md`, GDPR section). This
list is meant to be published to customers (SECURITY.md promises a public list of sub-processors)
once the owner has confirmed every row and the change-notification period below.

## Deployment variants

The platform has two deployment variants (ADR-0002, ADR-0017, ADR-0018). Which rows apply to a
customer depends on the variant that customer is on.

| Sub-processor | Purpose | Data involved | Variant | Location (per repository docs) | DPA signed | To be confirmed by the owner |
|---|---|---|---|---|---|---|
| Supabase | PostgreSQL + pgvector, Storage (S3-compatible), Auth | All tenant data, uploaded files, user e-mail addresses | Supabase pilot | ADR-0017: project in the EU, Frankfurt | To be confirmed by the owner | Legal entity, contract/DPA status, actual project region, Supabase's own sub-processors, backup location |
| Fly.io | Container hosting of the all-in-one process | Data in transit and in memory; no persistent customer data intended | Supabase pilot | ADR-0017: region `fra` | To be confirmed by the owner | Legal entity, contract/DPA status, whether volumes or logs hold customer data, log retention |
| Amazon Web Services | Compute, S3, SQS, KMS, Cognito, logging | All tenant data | AWS | ADR-0002: `eu-central-1` primary, `eu-west-1` backups | To be confirmed by the owner | AWS account/contract (not deployed yet per the audit), DPA acceptance, SCP region guard in place |
| LLM provider(s) behind the LLM gateway | Language-model inference for BOM generation and validation | Extracts of design files and knowledge-base text sent in prompts | Both | ADR-0006 lists candidates: Amazon Bedrock (EU), Azure OpenAI (EU Data Zone), Mistral (EU), self-hosted open-weight models | To be confirmed by the owner | Which providers are actually enabled in production, DPA and zero-retention / no-training terms, confirmed EU processing per model |
| E-mail relay (invitations) | Sending invitation e-mails | Invitee e-mail address | Optional | Operator's choice; no default host in the code | To be confirmed by the owner | Whether one is used, which vendor, region, DPA |
| Observability back-ends (OpenTelemetry, Langfuse) | Traces, metrics, LLM traces | Pseudonymous identifiers; prompts only within the tenant space (SECURITY.md) | Both | To be confirmed by the owner | To be confirmed by the owner | Whether a hosted service is used or self-hosted, region, retention |
| Identity providers chosen by customers (SSO, social login) | Sign-in federation | Name, e-mail | Optional | Customer-controlled | Customer's own contract | Whether any social login (Google, Microsoft, Apple) is enabled in production and the controller/processor split |

## Rules the platform applies to every sub-processor (from the repository)

- Processing in the EU only; no endpoints outside the allowlist (CLAUDE.md rule 2, ADR-0002, ADR-0006).
- No learning across organisations and no fine-tuning on customer data (CLAUDE.md rule 3).
- Customer files and documentation are untrusted content (CLAUDE.md rule 5).

## Change notification

To be decided by the owner: how and how far in advance customers are told about a new or replaced
sub-processor (a typical DPA gives 14 to 30 days and a right to object). Until decided, do not
promise a period.

## In-app link

The web app does not link to this list yet: it needs a public URL, which is an owner decision
(hosting of the legal pages). Once the list is published, add the link to the Settings screen and
the sign-in page in both locales (PL and EN).

## Maintenance

Update this file in the same pull request that adds or removes a vendor, an LLM provider or a
region. Owner: the person who signs the DPAs.
