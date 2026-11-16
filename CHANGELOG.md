# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). No release has been tagged yet (all modules are
`0.1.0`); everything below is therefore under "Unreleased". Entries are derived from the merged pull request titles
(`git log origin/main`); `docs/STATUS.md` has the per-milestone detail. Tagging is an owner decision.

## [Unreleased]

### Added
- M0-M7 platform: tenant context with RLS, API, ingest/agent/KB workers, parsers, variants A and B, evaluation
  harness, web app, AWS CDK and Supabase/Fly deployment paths (#1).
- EU-only LLM gateway for the Fly + Supabase pilot (#7); pilot virtual-key script and key rotation runbook (#26).
- Social sign-in (Google, Microsoft, Apple) in the web app (#6); Google and Microsoft buttons enabled on the pilot (#14).
- Sample data pack seeded into every organisation (#11).
- Visible demo mode: banner, CSV watermark, demo flag (#18).
- Per-IP abuse protection before the organisation context (#19); streamed uploads (#20).
- Hardened parse child process (#21); malware scan of uploaded files before parsing, EICAR default and optional ClamAV (#46).
- OpenTelemetry metrics for runs, LLM usage, parsing and dead letters (#22).
- Caller address in audit events (#23); daily audit-chain anchors in write-once storage (#24).
- Process roles (all / web / worker) for the all-in-one image (#27).
- ADR-0018 deployment tiers (proposed) and a pending-decisions check (#25).
- `SECURITY.md`, `CODEOWNERS`, idempotency key TTL sweep (#39).
- Localised API errors, panel focus management and an accessibility regression gate in the web app (#43).
- Restore drill script and DR/incident runbooks (#45).
- `just doctor`, `CONTRIBUTING.md`, `bomagent-ops` skeleton, docs-only CI fast path (#42).
- Cassette recorder, nightly eval workflow and property-based tests (#44).
- Evaluation tooling for the thesis: attempted MPN hallucination rate as the primary metric (#29), price provenance
  and sampling info (#31), retrieval stack and knowledge-base snapshot in the manifest (#32), error classes and
  per-rule coverage (#33, #34), Holm correction, cluster bootstrap and effect sizes (#35), verifier agreement and
  dataset hygiene (#36).
- Fable audit of the platform and thesis (EN + PL) with a progress tracker (#16, #17).
- `docs/platform/AS_BUILT.md`: what is built versus `ARCHITECTURE.md`, with evidence paths (ARCH-09).

### Changed
- Mistral pinned to the EU regional endpoint `api.eu.mistral.ai` (#10).
- Hashing embeddings are refused outside local/test unless opted in (#40).
- `/docs` and `/openapi.json` are served only in local, test and dev (#38).
- Supabase pilot values in `fly.toml` (#5).

### Documentation
- Production SaaS architecture, ADRs, UX guidelines and the Claude Code master prompt; single-source-of-truth
  workflow; evaluation dataset candidates.
- Owner checklist for the live pilot (#13); EU LLM key guide (#8); social login status runbook (#9).
