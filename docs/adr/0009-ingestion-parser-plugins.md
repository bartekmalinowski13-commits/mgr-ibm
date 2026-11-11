# ADR-0009: Ingestion: parser plugins in an isolated worker

Status: Accepted · 2026-11-09

## Context
Required formats: KiCad, Altium, Cadence OrCAD/Allegro, PDF, DXF/DWG; some of the formats are closed and binary.

## Decision
A `FormatParser` plugin interface (detection, parsing, confidence level). Order of paths: open format → native parser; closed format → open-source parser after a spike (with a licence assessment) → neutral export from the customer's tool (IPC-2581, ODB++, EDIF, CSV BOM). A worker without network, read-only, non-root, resource limits, malware scan before parsing.

## Consequences
Safe processing of untrusted files, easy addition of formats. Honesty towards the customer: the UI says when an export is needed.

## Alternatives considered
Parsing in the API process (security and stability risk).
