#!/usr/bin/env bash
# Deploy one environment from CI (never from a laptop or an agent session - CLAUDE.md §6).
# Expects AWS credentials of the environment's GitHub deploy role in the environment and:
#   ENV=dev|staging|prod  AWS_ACCOUNT_ID  IMAGE_REGISTRY  IMAGE_TAG  [DOMAIN_NAME]
set -euo pipefail
: "${ENV:?}" "${AWS_ACCOUNT_ID:?}" "${IMAGE_REGISTRY:?}" "${IMAGE_TAG:?}"
REGION=eu-central-1
PREFIX="BomAgent-${ENV}"
CTX=(-c "bomagent:env=${ENV}" -c "bomagent:account=${AWS_ACCOUNT_ID}"
     -c "bomagent:imageRegistry=${IMAGE_REGISTRY}" -c "bomagent:imageTag=${IMAGE_TAG}")
[ -n "${DOMAIN_NAME:-}" ] && CTX+=(-c "bomagent:domainName=${DOMAIN_NAME}")

out() { # out <stack> <output key>
  aws cloudformation describe-stacks --region "${2:-$REGION}" --stack-name "$1" \
    --query "Stacks[0].Outputs[?starts_with(OutputKey, '$3')].OutputValue | [0]" --output text
}

echo "::group::cdk deploy (${ENV})"
APP_URL=$(out "${PREFIX}-Edge" "$REGION" Url 2>/dev/null || true)
[ "$APP_URL" = "None" ] && APP_URL=""
if [ -n "$APP_URL" ]; then CTX+=(-c "bomagent:appUrl=${APP_URL}"); fi
pnpm --filter @bomagent/infra exec cdk deploy --all --require-approval never "${CTX[@]}"
if [ -z "$APP_URL" ]; then # first deployment: point the Cognito callback at CloudFront
  APP_URL=$(out "${PREFIX}-Edge" "$REGION" Url)
  pnpm --filter @bomagent/infra exec cdk deploy "${PREFIX}-Identity" --require-approval never \
    "${CTX[@]}" -c "bomagent:appUrl=${APP_URL}"
fi
echo "::endgroup::"

echo "::group::database migrations"
TASK_DEF=$(out "${PREFIX}-Compute" "$REGION" MigrationTaskDefinition)
SG=$(out "${PREFIX}-Compute" "$REGION" MigrationSecurityGroup)
SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=tag:aws-cdk:subnet-name,Values=isolated" "Name=tag:environment,Values=${ENV}" \
  --query 'Subnets[].SubnetId' --output text | tr '\t' ',')
TASK=$(aws ecs run-task --region "$REGION" --cluster "bomagent-${ENV}" --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --region "$REGION" --cluster "bomagent-${ENV}" --tasks "$TASK"
CODE=$(aws ecs describe-tasks --region "$REGION" --cluster "bomagent-${ENV}" --tasks "$TASK" \
  --query 'tasks[0].containers[0].exitCode' --output text)
[ "$CODE" = "0" ] || { echo "migration task failed (exit ${CODE})"; exit 1; }
echo "::endgroup::"

echo "::group::web app"
BUCKET=$(out "${PREFIX}-Edge" "$REGION" SiteBucket)
DIST=$(out "${PREFIX}-Edge" "$REGION" DistributionId)
URL=$(out "${PREFIX}-Edge" "$REGION" Url)
pnpm --filter @bomagent/web run build
cat > apps/web/dist/config.json <<JSON
{"auth": {"mode": "oidc",
  "domain": "$(out "${PREFIX}-Identity" "$REGION" HostedLogin)",
  "clientId": "$(out "${PREFIX}-Identity" "$REGION" OidcAudience)",
  "redirectUri": "${URL}/auth/callback", "logoutUri": "${URL}/login"}}
JSON
aws s3 sync apps/web/dist "s3://${BUCKET}" --delete --cache-control "public,max-age=31536000,immutable" --exclude index.html --exclude config.json
aws s3 cp apps/web/dist/index.html "s3://${BUCKET}/index.html" --cache-control "no-cache"
aws s3 cp apps/web/dist/config.json "s3://${BUCKET}/config.json" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths /index.html /config.json >/dev/null
echo "::endgroup::"

echo "::group::smoke"
curl -fsS "${URL}/" -o /dev/null
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${URL}/v1/me")
[ "$STATUS" = "401" ] || { echo "API through CloudFront answered ${STATUS}, expected 401"; exit 1; }
echo "deployed ${ENV}: ${URL}"
echo "::endgroup::"
