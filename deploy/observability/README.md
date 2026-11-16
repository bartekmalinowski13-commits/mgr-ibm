# Observability of the pilot (audit OPS-01 / OPS-02)

What the application sends: **traces** and **metrics** over OTLP/HTTP to
`BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT` (traces to `<endpoint>/v1/traces`, metrics to
`<endpoint>/v1/metrics` every 30 s), structured JSON logs to stdout. Nothing is sent until the
endpoint is set. EU only (CLAUDE.md rule 2): use an EU collector (Grafana Cloud with an EU stack,
or a self-hosted collector in Fly region `fra`).

## What you do (owner)

1. Create the backend account and an **EU** stack (Grafana Cloud: region `eu`, e.g. Frankfurt).
   Create an OTLP token for it.
2. On the main app: `fly secrets import -a mgr-ibm-bomagent` with, on stdin,
   `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64 instance-id:token>` (the standard
   OpenTelemetry variable, read by both exporters; it is a secret, so never in `fly.toml`) and set
   `BOMAGENT_OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-<region>.grafana.net/otlp` in
   `fly.toml` `[env]` (not secret). Use the same for the worker group (same app, same secrets).
3. Import `dashboards/bomagent-overview.json` (Dashboards -> New -> Import) and `alerts.yml`
   (Alerting -> Alert rules -> Import), connect a contact point (e-mail or phone).
4. Add an **outside probe** (Grafana Synthetic Monitoring from an EU location, or a free uptime
   service with EU nodes) on `https://mgr-ibm-bomagent.fly.dev/readyz`, expecting 200 and
   `"status":"ok"`; alert after 2 failures in a row. The application cannot report its own
   outage.
5. Error tracking (optional): Sentry in the EU region or GlitchTip, with PII scrubbing on; not
   wired in code yet.

## Metrics the code records (`bomagent_common.metrics`)

| Metric | Type | Labels |
|---|---|---|
| `bomagent_runs_total` | counter | `status` (completed, failed, ...), `variant` |
| `bomagent_run_duration_s` | histogram | `variant` |
| `bomagent_llm_calls_total` | counter | `model` |
| `bomagent_llm_tokens_total` | counter | `model`, `tenant`, `direction` (input/output) |
| `bomagent_llm_cost_eur_total` | counter | `model`, `tenant` |
| `bomagent_parse_total` | counter | `outcome` (ok/failed), `code` (e.g. `parse.timeout`) |
| `bomagent_parse_duration_s` | histogram | - |
| `bomagent_outbox_sent_total`, `bomagent_outbox_dead_total` | counter | - |
| `bomagent_queue_dead_total` | counter | `queue` |

Units are part of the names, so the Prometheus-style names equal these (histograms add
`_bucket`/`_sum`/`_count`). HTTP RED metrics come from the FastAPI auto-instrumentation; their
exact names depend on the installed OpenTelemetry semantic-conventions version
(`http_server_duration_milliseconds_*` today, `http_server_request_duration_seconds_*` in newer
versions): adjust the two HTTP expressions in the dashboard and `alerts.yml` if your backend
shows the other name. Web and worker processes report as `bomagent-allinone-web` /
`bomagent-allinone-worker` (`service.name`).

Not yet available (follow-up): queue depth and age gauges, outbox pending gauge (OPS-03), Fly
OOM events (use Fly's own metrics, `fly_instance_memory_*`, or `fly logs` for `Out of memory`),
alert "no anchor written today" (the daily anchor export only logs
`audit_anchor_export_failed`).

## Consistency check

`tests/tools/test_observability_assets.py` fails when the dashboard or an alert references a
`bomagent_*` metric that `metrics.py` does not define.
