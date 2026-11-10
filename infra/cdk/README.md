# infra (`@bomagent/infra`)

AWS infrastructure of BOM Agent as code (ADR-0013: CDK v2, TypeScript, cdk-nag).

> **Never deployed from a Claude Code session or a laptop** (CLAUDE.md §6). This package
> only synthesises CloudFormation and tests it. Deployment is a human-run pipeline job
> with a GitHub OIDC role, disabled until `vars.AWS_DEPLOY_ENABLED == 'true'`.

- **Stacks per environment** (`-c bomagent:env=dev|staging|prod`): network (VPC with
  public/app/isolated tiers, VPC endpoints incl. Bedrock, flow logs), data (Aurora
  PostgreSQL 16 Serverless v2 with KMS and TLS-only, files bucket, audit archive with
  Object Lock, SQS queues + DLQs) - further stacks follow `docs/plans/M6-infrastructure.md`.
- **Synth without credentials:** no `fromLookup`; account and other values come from
  context (`-c bomagent:account=123456789012 -c bomagent:imageRegistry=...`) with a
  placeholder account for local synth; availability zones are fixed per region.
- **Compliance:** cdk-nag `AwsSolutions` runs as a validation plugin; every acknowledged
  finding carries a written reason in code (`lib/nag.ts`).
- **Organisation guardrails:** `policies/scp-*.json` (EU regions only, no disabling of
  CloudTrail/GuardDuty/Security Hub/Config, no public buckets, no root) - applied by a
  human in AWS Organizations.

## Test
```bash
pnpm --filter @bomagent/infra run typecheck test lint
just synth        # cdk synth --all (fails on cdk-nag findings)
```
