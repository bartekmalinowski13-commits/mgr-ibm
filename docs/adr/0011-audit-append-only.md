# ADR-0011: Audit: append-only log with a hash chain and Object Lock

Status: Accepted · 2026-11-09

## Context
Customers work under the ISO 13485 regime – traceability of who changed the BOM and why is needed.

## Decision
An append-only `audit_events` table (permissions + a trigger blocking UPDATE/DELETE), `prev_hash`/`hash` fields; daily export to S3 with Object Lock (compliance). Provenance of every BOM item (rule + version / model + prompt + citations).

## Consequences
Provable log integrity; data for customer inspections. Cost: storage.

## Alternatives considered
CloudTrail only (does not see domain operations).
