# Changing the embedding model: re-index procedure (audit DATA-02)

`kb.chunks.embedding` is `vector(1024) NOT NULL` with one HNSW index (`chunks_embedding`,
cosine) and every chunk records the model that produced it in `embedding_model`. Vectors of
different models are **not comparable**, so a model change is a re-index, never an in-place
switch of the setting. Retrieval embeds the query with the *configured* model
(`BOMAGENT_EMBEDDING_MODEL`); querying chunks of another model returns meaningless distances.

## Which case are you in?

| New model | Dimension | Procedure |
|---|---|---|
| Same dimension (1024), e.g. a new version | 1024 | A: re-index in place |
| Different dimension (e.g. 768, 1536, 3072) | != 1024 | B: new column or table (needs a migration and an ADR) |

## A. Same dimension: re-index in place

Retrieval must never mix models inside one search. The knowledge base is per tenant, so migrate
tenant by tenant while the others keep working.

1. **Enable the model** in the LLM gateway catalog (EU only, ADR-0002/0006) and verify it with
   `GatewayEmbeddings` against a few sentences (dimension must be exactly 1024).
2. **Freeze the setting:** keep `BOMAGENT_EMBEDDING_MODEL` at the old model while re-indexing.
3. **Re-embed** every document of one tenant with the new model into a staging copy: the
   `KnowledgeBase` indexing path (`bomagent_kb.store`) writes `embedding_model` with every
   chunk; re-run the indexing of a tenant's documents with an embedder configured for the new
   model, in a maintenance window. (A ready-made re-index command does not exist yet: this is
   the first thing to build before the first model change.) Never fine-tune or share vectors
   across tenants (CLAUDE.md rule 3).
4. **Switch per tenant** in one transaction: replace the tenant's chunk rows by the staged ones
   (`DELETE`/`INSERT` under the tenant's RLS context), then set the setting to the new model
   once **all** tenants are done (or keep a per-tenant model setting, see below).
5. **Verify:** `SELECT embedding_model, count(*) FROM kb.chunks GROUP BY 1` shows one model per
   tenant; run the retrieval evals (`bomagent experiment`) and compare recall with the old
   model. KB snapshots (ARCH-06, `kb.snapshots`) include the model in their id, so runs pinned to
   an old snapshot stay reproducible only while the old chunks exist: **do not delete the old
   rows before the last pinned experiment is exported**.
6. **Rollback:** keep the old rows (as a copy table) until the evals pass; restoring is the
   same swap in the other direction plus the setting.
7. `REINDEX INDEX CONCURRENTLY kb.chunks_embedding` afterwards (HNSW quality after a large
   rewrite), outside peak hours.

## B. Different dimension

Do not `ALTER COLUMN ... TYPE` (full rewrite under an ACCESS EXCLUSIVE lock, and the
migration lint forbids it). Follow expand/contract (`packages/py/db-migrations/README.md`):

1. **Expand:** add a per-model table, e.g. `kb.chunk_embeddings (chunk_id, tenant_id, model,
   embedding vector(N)/halfvec(N), PRIMARY KEY (chunk_id, model))` with forced RLS
   (`tenant_table_rls`) and its own HNSW index per model; chunks keep their text and
   metadata. `halfvec` halves the storage and index size (pgvector >= 0.7) and is worth it
   above 1024 dimensions (HNSW limit: 2000 for `vector`, 4000 for `halfvec`).
2. Backfill in batches per tenant; retrieval reads the table of the tenant's configured model.
3. **Contract** (a later release): drop `kb.chunks.embedding` when no model uses it.

New ADR required (decision: per-model table vs. column), plus the retrieval change in
`bomagent_kb` and a per-tenant `embedding_model` setting so tenants can migrate one by one.

## Checklist before any model change

- [ ] model is EU-processed and in the gateway allowlist;
- [ ] dimension known and recorded (case A or B);
- [ ] evals run on the new model (recall, injection suspects);
- [ ] old vectors kept until pinned snapshots are exported.
