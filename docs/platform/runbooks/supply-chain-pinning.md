# Supply chain: pinning base images by digest (SEC-10)

Why: `python:3.12-slim-bookworm`, `node:22-bookworm-slim` and `ghcr.io/berriai/litellm:v1.108.3` are mutable tags; a rebuild can silently pull different content. Pinning by digest makes builds reproducible, and Dependabot (`package-ecosystem: docker` for `/deploy/docker` is already configured) proposes digest bumps.

`deploy/docker/*` is reserved for the owner, so this is a checklist for a human, not something a Claude Code session does.

## Checklist
1. For each of the three images, resolve the current multi-arch index digest (the pipeline builds linux/arm64 and CI amd64, so use the index, not a single-platform manifest): `docker buildx imagetools inspect python:3.12-slim-bookworm` (the `Digest:` of the top-level index), likewise `node:22-bookworm-slim` and `ghcr.io/berriai/litellm:v1.108.3`.
2. In `deploy/docker/allinone.Dockerfile`, `python-service.Dockerfile` and `llm-gateway.Dockerfile` change the `ARG` defaults to `name:tag@sha256:<digest>` (keep the tag for readability; the digest wins). The `ARG PYTHON_IMAGE` default appears in all three files.
3. Check that nothing overrides the args: `grep -rn "PYTHON_IMAGE\|NODE_IMAGE\|LITELLM_IMAGE" .github deploy tools`.
4. Build all three locally (the commands are in each file header) and run `just smoke`.
5. Confirm Dependabot's docker ecosystem picks the digests up (the next weekly PR should bump `@sha256:`).
6. Run the `supply-chain` workflow (workflow_dispatch) and compare the Trivy image findings before and after.
7. Later, separately: cosign keyless signing of pushed images and verification in `tools/deploy.sh` (not part of this change).

## Related checks (report-only, not required yet)
- `.github/workflows/supply-chain.yml`: licence gate (AGPL/SSPL fail, unknown licences warn) and Trivy image scan.
- `.github/workflows/sast.yml`: Bandit.
Promote a job to a required check in branch protection only after it has been green and its baseline triaged.
