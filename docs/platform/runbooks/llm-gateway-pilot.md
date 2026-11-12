# Runbook: real EU LLMs in the Fly.io + Supabase pilot

Goal: the pilot (`https://mgr-ibm-bomagent.fly.dev`) calls real models through a LiteLLM
gateway that runs as a second Fly app (`mgr-ibm-llm-gateway`, region `fra`, **no public
port**). Everything stays in the EU (CLAUDE.md rule 2, ADR-0006). Nothing here is done by
Claude Code: you run these steps. Secrets are only ever set with `fly secrets set`, never
committed. `<...>` = placeholder for a value you create.

```
browser -> mgr-ibm-bomagent (Fly, public) -- http over 6PN --> mgr-ibm-llm-gateway.internal:4000 (Fly, private)
                                                                  |-> api.eu.mistral.ai (EU regional inference)
                                                                  |-> Azure OpenAI, EU data-zone resource
                                                                  |-> Bedrock eu-central-1 (eu. inference profiles)
```

What protects you: the gateway config is rendered **from the catalogue at image build time**
(only `enabled: true` and `verified: true` entries) and `bomagent_llm.eu_guard` fails the
build on a non-EU region, a non-`eu.` Bedrock profile or a foreign endpoint (US regions,
`us.`/`global.` profiles, Alibaba/DashScope, api.openai.com ...). The app refuses to start
without a gateway unless `BOMAGENT_ALLOW_FAKE_LLM=true`.

## A. Provider accounts (EU)

1. **Mistral La Plateforme.** Create an account at <https://console.mistral.ai>, create a
   workspace, add billing, create an API key (`<MISTRAL_KEY>`). Only the regional endpoint
   `https://api.eu.mistral.ai` guarantees EU inference processing; the default
   `api.mistral.ai` does **not**, and the gateway config therefore pins
   `api_base: https://api.eu.mistral.ai/v1` (the EU guard rejects anything else). EU regional
   inference carries a surcharge of about +10 % (check the current terms at
   <https://docs.mistral.ai/inference/regional-inference>) and covers **inference only** -
   account, billing and console data are not covered by it. Note the exact model id from
   `GET https://api.eu.mistral.ai/v1/models` (the catalogue uses
   `mistral/mistral-large-latest`; pin an exact id if you prefer) and check the key works
   against the EU endpoint.
2. **Azure OpenAI (OpenAI models).** In the Azure portal create an *Azure OpenAI* /
   Foundry resource in an EU region (`swedencentral`, `francecentral` or
   `germanywestcentral`). Create a model deployment of type **Data Zone Standard (EU)** -
   never "Global". Note the **deployment name** (`<AZURE_DEPLOYMENT>`), the resource
   endpoint `https://<resource>.openai.azure.com` (`<AZURE_API_BASE>`) and a key
   (`<AZURE_KEY>`). The catalogue expects the deployment name `bomagent-gpt-eu-datazone`
   in `swedencentral`; if yours differs, change `gateway_model` / `region` of `openai-eu`.
3. **AWS Bedrock (Claude, Qwen).** In an AWS account open Bedrock in **eu-central-1**
   (Frankfurt) and request model access for Anthropic Claude (Opus/Sonnet/Haiku 5.5) and,
   if wanted, Qwen3 235B. Then create an IAM user `bomagent-llm-gateway` (programmatic access
   only, no console) with a policy limited to `bedrock:InvokeModel` and
   `bedrock:InvokeModelWithResponseStream` on the **EU** resources only:
   the `eu.*` inference-profile ARNs in eu-central-1 and the foundation-model ARNs in
   `eu-central-1`, `eu-north-1`, `eu-south-1`, `eu-south-2`, `eu-west-1`, `eu-west-3`
   (the `eu.` profiles route only there). Add a Region condition
   (`aws:RequestedRegion` in those regions) as a second barrier. Create an access key
   (`<AWS_KEY_ID>`, `<AWS_SECRET>`). Check the profile's real destinations from
   Frankfurt: `aws bedrock get-inference-profile --region eu-central-1
   --inference-profile-identifier eu.anthropic.claude-sonnet-5-5` and confirm every region
   in `models[].modelArn` is an EU member-state region.

## B. Gateway app on Fly

4. Create the app (no deploy yet, no public IP is allocated because the config has no service):
   `fly apps create mgr-ibm-llm-gateway --org <YOUR_ORG>`. It must be in the **same Fly
   organisation** as `mgr-ibm-bomagent` (6PN networks are per organisation).
5. Optional but recommended - a database for virtual keys: LiteLLM stores virtual keys
   and budgets in PostgreSQL. Create an empty database `litellm` with its own role on an
   EU Postgres (e.g. on the Supabase project, role without access to the `bomagent`
   database) and use its URL in step 6. Without `DATABASE_URL` virtual keys do not work -
   see the stop-gap in step 9.
6. Set the secrets (values are placeholders; run once, only the providers you use):
   ```bash
   fly secrets set -a mgr-ibm-llm-gateway \
     LITELLM_MASTER_KEY="sk-<long-random-string>" \
     DATABASE_URL="postgresql://<litellm-role>:<password>@<eu-host>:5432/litellm?sslmode=require" \
     MISTRAL_API_KEY="<MISTRAL_KEY>" \
     AZURE_API_KEY="<AZURE_KEY>" AZURE_API_BASE="https://<resource>.openai.azure.com" \
     AWS_ACCESS_KEY_ID="<AWS_KEY_ID>" AWS_SECRET_ACCESS_KEY="<AWS_SECRET>" \
     AWS_REGION_NAME="eu-central-1"
   ```
   `LITELLM_MASTER_KEY` must start with `sk-`; generate it with `openssl rand -hex 32`.
7. Enable the models you verified (section C) **before** building: only entries with
   `enabled: true` and `verified: true` are rendered into the image.

## C. Enable models in the catalogue

8. In `packages/py/llm/src/bomagent_llm/catalog/models.yaml` check each entry you want
   (exact `gateway_model` id, `region`, availability in *your* account) and flip `enabled`
   and `verified` to `true`. Run `uv run pytest packages/py/llm` and
   `uv run python -m bomagent_llm.gateway_config` (the EU guard must pass). Commit via a PR
   (`feat/...`), merge, then deploy from `main`.

## D. Deploy the gateway and create the key

9. Deploy (repository root):
   `fly deploy . --config deploy/supabase/gateway.fly.toml --dockerfile deploy/docker/llm-gateway.Dockerfile --ha=false`
   Check: `fly status -a mgr-ibm-llm-gateway`, `fly logs -a mgr-ibm-llm-gateway`.
   Test from your machine through a private tunnel: `fly proxy 4000:4000 -a mgr-ibm-llm-gateway`
   then `curl -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:4000/v1/models`.
10. Create the **virtual key** for the app (through the proxy tunnel; needs `DATABASE_URL`):
    ```bash
    curl -s localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{"key_alias":"bomagent-pilot","models":["<gateway_model of each enabled entry>"],"max_budget":20,"duration":"90d"}'
    ```
    Copy the returned `key` (`sk-...`) - it is shown once. Stop-gap if you skipped step 5:
    use the master key as the app key **temporarily** and note it in your risk list (it can
    administer the gateway).

## E. Switch the pilot over

11. Point the app at the gateway and remove the fake-provider switch:
    ```bash
    fly secrets set -a mgr-ibm-bomagent BOMAGENT_LLM_GATEWAY_KEY="<virtual key>"
    fly secrets set -a mgr-ibm-bomagent BOMAGENT_LLM_GATEWAY_URL="http://mgr-ibm-llm-gateway.internal:4000"
    ```
    (`http` is accepted by the app **only** for `*.internal` hosts.) Then delete the line
    `BOMAGENT_ALLOW_FAKE_LLM = "true"` from `deploy/supabase/fly.toml` (PR) and redeploy the
    app: `fly deploy . --config deploy/supabase/fly.toml --dockerfile deploy/docker/allinone.Dockerfile --ha=false`.
    Embeddings: if you enabled an embedding entry (e.g. `titan-embed-v2-eu`) also
    `fly secrets set -a mgr-ibm-bomagent BOMAGENT_EMBEDDING_MODEL="<gateway_model>"`;
    the default `fake-embedding` is not served by the gateway.
12. Verify: `curl -s https://mgr-ibm-bomagent.fly.dev/readyz` shows `"llm":"gateway"` and
    `"status":"ok"`. If the app crash-loops, `fly logs` names the missing variable
    (the app refuses to start with only one of URL/KEY, or neither without
    `BOMAGENT_ALLOW_FAKE_LLM`).
13. Smoke run: sign in, create a project, upload the ECG KiCad fixture
    (`packages/py/testing/.../ecg-frontend`), start one run of variant B with an enabled model
    and check that a BOM appears. In the gateway logs (`fly logs -a mgr-ibm-llm-gateway`)
    you see the request for the model; in the run's trace the model id is the catalogue id,
    not `fake-closed`.

## Qwen

Alibaba's own API is **not** supported (no EU processing guarantee). EU-resident options:
Bedrock in-region (eu-central-1, eu-north-1, eu-south-1; entry `qwen3-235b-bedrock-eu`) or
self-hosted vLLM in an EU region (entry `qwen3-vllm-self-hosted`, not rendered by the cloud
gateway yet). Mistral does not host Qwen. Azure AI Foundry EU availability was not verified.

## Rollback

`fly secrets unset -a mgr-ibm-bomagent BOMAGENT_LLM_GATEWAY_URL BOMAGENT_LLM_GATEWAY_KEY`
and put `BOMAGENT_ALLOW_FAKE_LLM = "true"` back in `fly.toml` to return to the fake model.
