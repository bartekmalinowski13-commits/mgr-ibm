# M2 – Knowledge base (plan)

Sources: ROADMAP M2, ADR-0006, ADR-0008, SECURITY.md (prompt injection), TESTING.md.

## Brainstorming – questions and answers
| Question | Decision | Rationale |
|---|---|---|
| Vector dimension | `vector(1024)` | Titan Text Embeddings V2 and Cohere Embed v3 (Bedrock) produce 1024; an HNSW index requires a fixed dimension |
| How to ensure reproducibility (`kb_snapshot_id`)? | immutable documents (`supersedes`), snapshot = list of active document ids | an experiment can be reproduced as long as the documents have not been deleted |
| Who writes to the global corpus? | only the `bomagent_platform` role (RLS policy), messages only from the platform pseudo-tenant | ADR-0008 |
| Docling – a mandatory dependency? | optional (kb-indexer image), tests on pypdf | Docling pulls in torch (GB); PyMuPDF rejected (AGPL) |
| Reranker | lexical (deterministic), interface ready for a reranker from the gateway | no network in CI; the same contract for a model-based reranker |
| Fake embeddings | feature hashing (words + trigrams) | deterministic retrieval tests without a model |
| Prompt injection in datasheets | sanitisation + `injection_suspect` flag, such fragments go to the end of the ranking | SECURITY.md |
| MPN catalog | `kb.parts` from extraction ("Ordering information" sections) + user corrections | basis of the MPN hallucination metric |

## Tasks (TDD) – status
1. `llm`: model catalog (EU, closed/open-weight, verification before enabling), gateway/hashing embeddings – ✅
2. Migration 0002 (`kb.documents/chunks/parts/snapshots`, global/tenant RLS, document-owner trigger) – ✅
3. `kb`: extraction, chunking, parts, security, store + hybrid retrieval + RRF + reranker, snapshots, corrections – ✅
4. `kb-indexer`: SQS handler (tenant/global), wiring from settings – ✅
5. Fixtures: 18 synthetic datasheets (CC0) + a set of 18 queries – ✅

## Acceptance criteria
Retrieval tests: recall@5 = 1.00, recall@1 = 0.89 (≥ 0.9 / ≥ 0.6 required in the test). KB isolation tests (`tests/isolation/test_kb_isolation.py`) green.
