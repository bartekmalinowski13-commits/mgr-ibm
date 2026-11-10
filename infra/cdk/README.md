# infra (`@bomagent/infra`)

AWS infrastructure of BOM Agent as code (ADR-0013: CDK v2, TypeScript, cdk-nag).

> **Never deployed from a Claude Code session or a laptop** (CLAUDE.md §6). This package
> only synthesises CloudFormation and tests it. Deployment is a human-run pipeline job
> with a GitHub OIDC role, disabled until `vars.AWS_DEPLOY_ENABLED == 'true'`.

- **Stacks per environment** (`-c bomagent:env=dev|staging|prod`):
  | Stack | Region | Contents |
  |---|---|---|
  | Network | eu-central-1 | VPC public/app/isolated, flow logs, S3 gateway + interface endpoints (SQS, Secrets Manager, ECR, Logs, KMS, STS, Bedrock) |
  | Data | eu-central-1 | Aurora PostgreSQL 16 Serverless v2 (KMS, TLS-only, IAM auth, pgaudit), role secrets, files bucket, audit archive (Object Lock), SQS + DLQs |
  | Identity | eu-central-1 | Cognito user pool, SPA client (code + PKCE, no secret), hosted login, threat protection |
  | Compute | eu-central-1 | ECS Fargate: API behind a CloudFront-only ALB, ingest (isolated subnets), agent and KB workers scaled on queue depth, LiteLLM gateway (EU-only Bedrock), migration task |
  | Waf | us-east-1 | WAF for CloudFront (global service, ADR-0002 exception): AWS managed rules + rate limit |
  | Edge | eu-central-1 | CloudFront: SPA from S3 via OAC, `/v1/*` to the ALB with a secret origin header, CSP/HSTS |
  | Observability | eu-central-1 | Alarms (DLQs, run backlog, API 5xx/CPU) to an encrypted SNS topic |
  | BackupCopy | eu-west-1 | Backup vault for cross-region copies |
  | Security | eu-central-1 | GuardDuty (S3 malware scan, ECS runtime), Security Hub (FSBP, CIS), Access Analyzer, CloudTrail (if no org trail), AWS Backup |
  | Cicd | eu-central-1 | GitHub OIDC provider + deploy role limited to the CDK bootstrap roles |
- **Synth without credentials:** no `fromLookup`; account and other values come from
  context (`-c bomagent:account=123456789012 -c bomagent:imageRegistry=...`) with a
  placeholder account for local synth; availability zones are fixed per region.
- **Compliance:** cdk-nag `AwsSolutions` runs as a validation plugin; every acknowledged
  finding carries a written reason in code (`lib/nag.ts`).
- **Organisation guardrails:** `policies/scp-*.json` (EU regions only, no disabling of
  CloudTrail/GuardDuty/Security Hub/Config, no public buckets, no root) - applied by a
  human in AWS Organizations.

## First deployment (human, from the pipeline)
1. `cdk bootstrap` in eu-central-1, us-east-1 and eu-west-1 of the workload account.
2. Deploy `Cicd`, set `vars.AWS_DEPLOY_ENABLED=true` and the role ARN in the GitHub environment.
3. Push images to the shared-services ECR (`bomagent-api`, `-ingest-worker`, `-agent-worker`,
   `-kb-indexer`, `-llm-gateway`, `-migrate`), deploy all stacks, run the migration task
   (`bomagent-migrate bootstrap` once, then `upgrade`), upload the SPA build to the site bucket.

## Test
```bash
pnpm --filter @bomagent/infra run typecheck test lint
just synth        # cdk synth --all (fails on cdk-nag findings)
```
