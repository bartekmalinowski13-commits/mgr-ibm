# ADR-0001: Monorepo and modular services instead of a monolith or fine-grained microservices

Status: Accepted · 2026-11-09

## Context
The project is meant to be modular (not a monolith), but it is developed by one person and AI agents, and part of the code must be shared by variants A and B of the experiment.

## Decision
A single monorepo (`uv` workspace + `pnpm` workspace). Domain code in `packages/py/*` libraries with boundaries enforced by `import-linter`. Four deployment services: `api`, `ingest-worker`, `agent-worker`, `kb-indexer` + ready-made components (`llm-gateway`, Langfuse, optionally `model-serving`). A new service only when it has a different security, scaling or release-cycle profile – justification in a new ADR.

## Consequences
Atomic cross-cutting changes, a single CI pipeline, shared tooling. Risk: CI growth – mitigated by path filters (`paths`) and building only the changed packages.

## Alternatives considered
Polyrepo (version coordination overhead); full microservices per domain (network, distributed transaction and operations overhead without benefit at this stage).
