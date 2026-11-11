# ADR-0003: ECS Fargate + SQS; Lambda only for glue; no Kubernetes

Status: Accepted · 2026-11-09

## Context
Needed: an API, long agent tasks (minutes), file processing, optionally GPU for open-weight models.

## Decision
ECS Fargate for the API, workers, gateway and Langfuse; SQS (+DLQ) as the work buffer, autoscaling by queue depth. Lambda only for reacting to events (e.g. an upload to S3). GPU (vLLM) – ECS with an EC2 GPU capacity provider, enabled by a flag. Kubernetes (EKS) – not now; revisit when there are >15 services or a need for custom operators.

## Consequences
Little operations work, pay for usage. Lambda is ruled out for agents (15 min limit, cold starts with heavy dependencies). Fargate does not support GPUs – hence the separate capacity provider.

## Alternatives considered
EKS (high operational overhead); Lambda + Step Functions for the whole flow (time and payload size limits, harder local testing).
