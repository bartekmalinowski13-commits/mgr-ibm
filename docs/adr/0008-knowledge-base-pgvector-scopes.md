# ADR-0008: Knowledge base: pgvector, global scope + per-tenant spaces

Status: Accepted · 2026-11-09

## Context
A single shared knowledge base, but organizations must not see or learn from each other's data.

## Decision
pgvector + Postgres full-text search (hybrid) + a reranker. A `scope` column (`global`|`tenant`), RLS: `tenant_id = current OR scope = 'global'`. Writes to `global` only by the platform pipeline. User corrections = tenant knowledge. A KB snapshot is stored with every run.

## Consequences
One database to maintain, transactional consistency with the rest of the data, isolation by the same mechanism as everything else. When vectors exceed ~50 million – an ADR on migration (OpenSearch Serverless).

## Alternatives considered
OpenSearch Serverless (a separate system, higher minimum cost); Pinecone (a sub-processor outside AWS).
