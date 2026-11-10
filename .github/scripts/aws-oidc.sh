#!/usr/bin/env bash
# Exchange the GitHub OIDC token for temporary AWS credentials of ROLE_ARN ($1) for
# DURATION seconds ($2, default 3600; at most the role's maximum session duration).
# Needs `permissions: id-token: write`. Credentials are masked and exported for later steps.
set -euo pipefail
command -v aws >/dev/null && command -v jq >/dev/null || { echo "AWS CLI v2 and jq are required on the runner"; exit 1; }
ROLE_ARN="${1:?role ARN}"
DURATION="${2:-3600}"
TOKEN=$(curl -fsS -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com" | jq -r .value)
CREDS=$(aws sts assume-role-with-web-identity --role-arn "$ROLE_ARN" \
  --role-session-name "github-${GITHUB_RUN_ID}" --web-identity-token "$TOKEN" \
  --duration-seconds "$DURATION" --query Credentials --output json)
for pair in AWS_ACCESS_KEY_ID:AccessKeyId AWS_SECRET_ACCESS_KEY:SecretAccessKey AWS_SESSION_TOKEN:SessionToken; do
  value=$(jq -r ".${pair#*:}" <<<"$CREDS")
  echo "::add-mask::${value}"
  echo "${pair%%:*}=${value}" >> "$GITHUB_ENV"
done
