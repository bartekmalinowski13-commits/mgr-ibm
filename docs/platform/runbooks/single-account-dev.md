# Runbook: first deployment in ONE AWS account (dev only)

The full layout (`README.md`, "first-deployment") uses seven accounts in AWS Organizations.
To get a working, shareable app quickly, start with **one account and only the `dev`
environment**. Everything below is done by the owner; Claude Code never deploys
(CLAUDE.md §6). Time: about 1-2 hours of setup + about 1 hour for the first pipeline run.

What this setup gives you: the full product in `eu-central-1` (CloudFront + WAF, ECS Fargate,
Aurora PostgreSQL, Cognito sign-in, SQS, S3, Bedrock in the EU), on the CloudFront address
(no own domain needed for dev). What it does not give you yet: SCP guardrails (they need AWS
Organizations - add them when you move to the multi-account layout), staging/prod.

Placeholders: `<ACCOUNT>` = your 12-digit account id, `<EMAIL>` = your e-mail,
`<REPO>` = `bartekmalinowski13-commits/mgr-ibm`.

## 1. Account and admin access (AWS console)

1. Create the AWS account, enable **MFA on the root user**, then stop using root.
2. IAM Identity Center (region `eu-central-1`): enable it, create a user for yourself with
   the `AdministratorAccess` permission set on this account, enable MFA for that user.
3. Billing -> Cost Explorer: enable it (needed for budget forecasts).

## 2. Your Mac

```bash
brew install awscli node pnpm
```

```bash
aws configure sso --profile bomagent-admin
```

(SSO start URL from IAM Identity Center, region `eu-central-1`.) Then in the repository:

```bash
pnpm install
```

## 3. CDK bootstrap (once)

```bash
AWS_PROFILE=bomagent-admin pnpm --filter @bomagent/infra exec cdk bootstrap aws://<ACCOUNT>/eu-central-1 aws://<ACCOUNT>/eu-west-1 -c bomagent:account=<ACCOUNT> -c bomagent:githubRepository=<REPO>
```

Do not bootstrap `us-east-1` (the WAF stack deploys without it).

## 4. Deploy the Cicd stack from your Mac (once)

It creates: the GitHub deploy role, the image repositories (ECR) with the push role, and a
**monthly cost budget** that e-mails you at 80 % of actual and 100 % of forecast spend.

```bash
AWS_PROFILE=bomagent-admin pnpm --filter @bomagent/infra exec cdk deploy BomAgent-dev-Cicd --exclusively -c bomagent:env=dev -c bomagent:account=<ACCOUNT> -c bomagent:githubRepository=<REPO> -c bomagent:singleAccount=true -c bomagent:monthlyBudgetUsd=150 -c bomagent:alarmEmail=<EMAIL>
```

Write down the three outputs: `DeployRoleArn`, `ImagesRoleArn`, `ImageRegistry`.

## 5. Bedrock model access (AWS console, `eu-central-1`)

Bedrock -> Model access -> request the models from
`packages/py/llm/src/bomagent_llm/catalog/models.yaml` (EU inference profiles). Then tell
Claude Code which models are enabled: it sets `enabled: true, verified: true` for them in
the catalogue (one commit). Without this step the app deploys but runs cannot call a model.

## 6. GitHub settings (repository -> Settings)

1. **Environments:** create `images` and `dev`; for each: "Deployment branches and tags" ->
   selected branches -> `main` only.
2. **Variables** (Settings -> Secrets and variables -> Actions -> Variables), all plain
   values, no secrets:

| Variable | Value |
|---|---|
| `AWS_ACCOUNT_ID` | `<ACCOUNT>` |
| `IMAGE_REGISTRY` | output `ImageRegistry` |
| `AWS_IMAGES_ROLE_ARN` | output `ImagesRoleArn` |
| `AWS_DEPLOY_ROLE_ARN` | output `DeployRoleArn` |
| `SINGLE_ACCOUNT` | `true` |
| `MONTHLY_BUDGET_USD` | `150` (same as in step 4) |
| `ALARM_EMAIL` | `<EMAIL>` |
| `DEPLOY_ENVIRONMENTS` | `dev` |
| `AWS_DEPLOY_ENABLED` | `true` (set this one **last**) |

## 7. Merge and deploy

Merge the PR into `main` (squash). The `main` workflow builds the images and runs
`tools/deploy.sh` for `dev`: CDK stacks, database roles and migrations, web app, smoke test.
The first run takes the longest (Aurora, CloudFront). Follow it in GitHub -> Actions; if a
step fails, copy the failing log into a Claude Code session - it fixes the code, you re-run.

## 8. First sign-in

The app URL is the CloudFront address: output `Url` of the `BomAgent-dev-Edge` stack
(CloudFormation console), also printed as `deployed dev: <URL>` at the end of the deploy log. Register with your
e-mail (Cognito sends a code), create the organisation - you are its owner. Invite testers
from Settings -> Members. Cognito's built-in e-mail sends at most 50 e-mails a day (enough
for testing; SES is the next step, see DECISIONS_LOG).

## 9. Costs and switching off

- The budget e-mails you; also check Billing -> Bills weekly at the start.
- Fixed costs of a running dev environment include Aurora Serverless v2 (minimum 0.5 ACU),
  one NAT gateway, VPC endpoints, the load balancer, Fargate tasks and WAF. Exact numbers
  depend on usage - watch the first week in Cost Explorer.
- To stop paying when you do not test for a longer time, destroy the environment (keeps the
  ECR images and retained buckets/backups, which you can delete in the console):

```bash
AWS_PROFILE=bomagent-admin pnpm --filter @bomagent/infra exec cdk destroy --all -c bomagent:env=dev -c bomagent:account=<ACCOUNT> -c bomagent:githubRepository=<REPO> -c bomagent:singleAccount=true -c bomagent:monthlyBudgetUsd=150 -c bomagent:alarmEmail=<EMAIL>
```

Set `AWS_DEPLOY_ENABLED=false` first so a push to `main` does not recreate it.

## Later: the full layout

Move to the multi-account layout of `README.md` (Organizations, SCPs, shared-services ECR,
staging, prod with a domain and certificates) before real customers.
