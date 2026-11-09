# ADR-0010: Obserwowalność: OpenTelemetry + Langfuse

Status: Zaakceptowany · 2026-11-09

## Kontekst
Wymagana pełna obserwowalność i monitoring, na otwartych standardach.

## Decyzja
OTel SDK w każdym serwisie, ADOT Collector, Amazon Managed Prometheus + Managed Grafana + CloudWatch/X-Ray w chmurze; `grafana/otel-lgtm` lokalnie. Langfuse self-hosted dla śladów LLM. Atrybut `tenant_id` na spanach. SLO + alarmy.

## Konsekwencje
Brak uzależnienia od jednego dostawcy obserwowalności; te same dane zasilają metryki pracy magisterskiej.

## Rozważane alternatywy
Datadog/New Relic (koszt, podprocesor danych); tylko CloudWatch (słabsze śledzenie LLM).
