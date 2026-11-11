# ADR-0010: Observability: OpenTelemetry + Langfuse

Status: Accepted · 2026-11-09

## Context
Full observability and monitoring required, on open standards.

## Decision
OTel SDK in every service, ADOT Collector, Amazon Managed Prometheus + Managed Grafana + CloudWatch/X-Ray in the cloud; `grafana/otel-lgtm` locally. Self-hosted Langfuse for LLM traces. A `tenant_id` attribute on spans. SLOs + alarms.

## Consequences
No lock-in to a single observability vendor; the same data feeds the master's thesis metrics.

## Alternatives considered
Datadog/New Relic (cost, a data sub-processor); CloudWatch only (weaker LLM tracing).
