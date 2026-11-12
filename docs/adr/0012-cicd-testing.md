# ADR-0012: CI/CD in GitHub Actions and the testing strategy

Status: Accepted · 2026-11-09

## Context
E2E and smoke tests required, and everything green before a release.

## Decision
The pipeline is described in `ARCHITECTURE.md §13` and `TESTING.md`. Trunk-based: short `feat/<module>-<description>` branches, PR, squash merge after green CI. Conventional Commits + release-please. Deploy via OIDC, disabled until AWS is configured.

## Consequences
Every change passes the same quality gate. Tests with an LLM are deterministic (fake provider / recordings).

## Alternatives considered
GitFlow (long-lived branches, conflicts).
