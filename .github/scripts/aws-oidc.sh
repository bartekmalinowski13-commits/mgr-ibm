#!/usr/bin/env bash
# Exchange the GitHub OIDC token for temporary AWS credentials of ROLE_ARN ($1).
# Needs `permissions: id-token: write`. Credentials are masked and exported for later steps.
set -euo pipefail
ROLE_ARN="${1:?role ARN}"
TOKEN=$(curl -fsS -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com" | jq -r .value)
CREDS=$(aws sts assume-role-with-web-identity --role-arn "$ROLE_ARN" \
  --role-session-name "github-${GITHUB_RUN_ID}" --web-identity-token "$TOKEN" \
  --duration-seconds 3600 --query Credentials --output json)
for pair in AWS_ACCESS_KEY_ID:AccessKeyId AWS_SECRET_ACCESS_KEY:SecretAccessKey AWS_SESSION_TOKEN:SessionToken; do
  value=$(jq -r ".${pair#*:}" <<<"$CREDS")
  echo "::add-mask::${value}"
  echo "${pair%%:*}=${value}" >> "$GITHUB_ENV"
done
