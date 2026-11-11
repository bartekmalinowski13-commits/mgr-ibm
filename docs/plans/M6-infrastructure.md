# M6 – Infrastructure (`infra/cdk`)

Overriding rule (CLAUDE.md §6): **code + `cdk synth` + tests**. No `cdk deploy`, no cloud resources from a Claude Code session. The deployment is run by a human from the pipeline (jobs disabled unless `vars.AWS_DEPLOY_ENABLED == 'true'`).

## Brainstorming (questions → answers from the documents)
| Question | Answer | Source |
|---|---|---|
| Tool | AWS CDK v2 (TypeScript) + cdk-nag (AwsSolutions, HIPAA Security as a reference point) | ADR-0013, ARCHITECTURE §12 |
| Stacks | network, data, identity, compute, observability, edge, security-baseline (+ cicd: GitHub OIDC role) | ADR-0013, ARCHITECTURE §13 |
| Region | `eu-central-1`; AWS Backup copies to `eu-west-1`; the WAF for CloudFront must be created in `us-east-1` (a global service – an exception allowed in ADR-0002) | ADR-0002, ARCHITECTURE §12 |
| Accounts | Organizations (management, security, log-archive, shared-services, dev/staging/prod) is set up by a human; the repo contains only the SCP policies (`infra/cdk/policies/`) to apply and the workload stacks for the dev/staging/prod accounts | ARCHITECTURE §12 |
| Synth without credentials | no `fromLookup`; account and parameters from context (`cdk.json`, CI variables) with the placeholder account `000000000000` in synth | CLAUDE.md §6 |
| Database | Aurora PostgreSQL 16 Serverless v2, KMS encryption, isolated subnets, IAM auth, Performance Insights with KMS, backtrack unavailable for PG – PITR + AWS Backup | ADR-0004, ADR-0008 |
| Queues | SQS ingest/runs/kb + DLQ (maxReceiveCount 5), SSE-KMS, TLS-only policy | ADR-0003 |
| Parsers | ingest-worker in an isolated subnet (no NAT), only VPC endpoints S3/SQS/Logs/ECR; read-only root FS, non-root | ADR-0009, CLAUDE.md §5 |
| LLM | LiteLLM as an ECS service with a VPC endpoint to Bedrock; egress to Azure OpenAI EU / Mistral via NAT (domain allowlist – Network Firewall as an option, out of v1 scope – see DECISIONS_LOG) | ADR-0006 |
| API behind CloudFront | ALB in public subnets, traffic only from CloudFront (the managed prefix list passed as a parameter – no lookups) + a secret origin header; WAF (AWS Managed Rules + rate limit) on CloudFront | SECURITY.md |
| SPA | private S3 + OAC, security headers (CSP, HSTS) via a Response Headers Policy | UX/SECURITY |
| Login | Cognito User Pool (e-mail verification, optional TOTP MFA → required for admins in the application, threat protection), SPA client without a secret with PKCE (authorization code), Hosted UI domain | ADR-0005 |
| Observability | log groups with KMS and retention, alarms (DLQ > 0, ALB 5xx, CPU, message age), SNS | ADR-0010 |
| Account security | GuardDuty (S3 Malware Protection, ECS Runtime Monitoring), Security Hub (FSBP, CIS), IAM Access Analyzer, account CloudTrail if there is no organization one (flag) | SECURITY.md |

## Task plan
1. The `infra/cdk` skeleton (the `@bomagent/infra` package, environment configuration, aspects: cdk-nag + tags), a test "synth of all stacks without cdk-nag errors".
2. network → data → identity → compute → edge (+ waf in us-east-1) → observability → security-baseline → cicd; for each: assertion tests (the most important security properties), then code.
3. `policies/scp-*.json` (EU only, no disabling CloudTrail/GuardDuty, no public buckets).
4. Cognito login (PKCE) in `apps/web` (configuration from `/config.json` generated at deployment).
5. `just synth`, CI (the `cdk` job), runbooks in `docs/platform/runbooks/`.
