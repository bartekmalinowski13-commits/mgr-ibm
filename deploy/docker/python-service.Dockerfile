# syntax=docker/dockerfile:1.7
# Shared image for Python services. Build args select the workspace package and module:
#   docker build -f deploy/docker/python-service.Dockerfile \
#     --build-arg PACKAGE=bomagent-api --build-arg MODULE=bomagent_api .
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ARG PACKAGE
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages/py ./packages/py
COPY services ./services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package "${PACKAGE}" --no-editable

# RDS/Aurora global CA bundle: services verify the database certificate (sslmode=verify-full,
# BOMAGENT_DB_SSL_ROOT_CERT is set by the CDK compute stack). Fetched over HTTPS at build time;
# pin the content with --build-arg RDS_BUNDLE_SHA256=<hex> for reproducible builds.
FROM ${PYTHON_IMAGE} AS rds-ca
ARG RDS_BUNDLE_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
ARG RDS_BUNDLE_SHA256=
RUN mkdir -p /out && python - <<'PY'
import hashlib, os, urllib.request
data = urllib.request.urlopen(os.environ["RDS_BUNDLE_URL"], timeout=60).read()
assert data.count(b"BEGIN CERTIFICATE") > 10, "unexpected RDS CA bundle"
want = os.environ.get("RDS_BUNDLE_SHA256", "")
assert not want or hashlib.sha256(data).hexdigest() == want, "RDS CA bundle checksum mismatch"
open("/out/global-bundle.pem", "wb").write(data)
PY

FROM ${PYTHON_IMAGE} AS runtime
ARG MODULE
ENV PATH="/src/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 BOMAGENT_MODULE=${MODULE}
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build --chown=root:root /src/.venv /src/.venv
COPY --from=rds-ca --chown=root:root /out/global-bundle.pem /etc/ssl/rds/global-bundle.pem
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
# shell form so the module comes from the build arg
CMD ["sh", "-c", "exec python -m ${BOMAGENT_MODULE}"]
