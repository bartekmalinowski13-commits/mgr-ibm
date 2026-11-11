# ADR-0006: LLM Gateway (LiteLLM) and providers with processing in the EU

Status: Accepted · 2026-11-09

## Context
Top-class closed models (Anthropic, OpenAI) and open models are required; everything in the EU; comparison in the thesis.

## Decision
All calls through LiteLLM. A model catalogue in configuration with the attributes `license_class` (closed/open-weight) and `residency`. Providers: Bedrock (Claude via the EU profile or in-region; open-weight models), Azure OpenAI in Data Zone Standard EU mode, Mistral (EU), self-hosted vLLM, Ollama in dev. Egress allowlist, per-tenant budgets, no training on customer data. Model IDs verified when enabling (regional availability changes).

## Consequences
A single point for enforcing policies and measuring cost; easy swapping of models in experiments. Risk: the gateway as a single point of failure – min. 2 tasks, health checks, fallback.

## Alternatives considered
Direct provider SDKs in code (scattered policies, hard to audit).
