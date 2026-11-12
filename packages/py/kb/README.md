# bomagent-kb (`bomagent_kb`)

**Responsibility:** knowledge base of component documentation (ADR-0008): extraction,
chunking, embeddings (through the LLM gateway), hybrid retrieval, part catalogue,
snapshots, global/tenant scopes.

## Public interface
- `extract(name, data, use_docling=False) -> ExtractedDocument` - PDF (pypdf text layer;
  Docling when installed in the kb-indexer image), text, Markdown. PyMuPDF is not used
  (AGPL).
- `KnowledgeBase(embedder, reranker)`; every method takes an `AsyncConnection` opened in
  the right RLS context (`tenant_transaction` / `platform_transaction`):
  - `add_document(conn, DocumentMeta, scope=Scope.TENANT|GLOBAL, created_by)` (dedup by SHA-256)
  - `index_document(conn, doc_id, extracted, extra_mpns=...)` - chunks + embeddings + part catalogue
  - `search(conn, query, k, snapshot_id, kinds)`, `search_many(...)` (one embeddings call)
  - `snapshot(conn) -> "kbs_..."` - frozen set of active documents (stored per run)
  - `add_correction(conn, mpn, manufacturer, note)` - a user's correction becomes **tenant** knowledge
  - `known_mpns(conn)`, `find_parts(conn, prefix)` - catalogue for MPN hallucination checks
  - `supersede`, `mark_failed`
- `Hit.citation()` -> `KbCitation` for BOM provenance.

## Isolation and safety
- RLS: `scope='global'` rows readable by all, writable only by `bomagent_platform`;
  tenant rows readable/writable only in their tenant's context; a trigger stops attaching
  chunks/parts to another tenant's document (FK checks bypass RLS).
- Document text is data: control/bidi characters are stripped, chunks that address the
  model ("ignore previous instructions...") are flagged `injection_suspect` and ranked last.
- Tenant mutations emit audit events (`kb.document.created/indexed/superseded`).

## Retrieval
pgvector cosine (HNSW, `vector(1024)`) + PostgreSQL FTS (`simple` config, OR of terms),
Reciprocal Rank Fusion (k=60), then `LexicalReranker` (overlap + exact MPN match). On the
synthetic fixture corpus: recall@5 = 1.00, recall@1 = 0.89 (18 queries) with the
deterministic hashing embedder; real embeddings are configured in the model catalogue.

## Testing
`uv run pytest packages/py/kb tests/isolation -m "integration"` (PostgreSQL + pgvector).
