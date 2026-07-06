# Bug Patterns — Database (migrations, Alembic lineage, DDL ownership)

Detailed write-ups for database/migration bug patterns indexed in
[`../BUG_PATTERNS.md`](../BUG_PATTERNS.md).

---

## BP-716 — `intelligence-migrations` does NOT own `nlp_db` DDL (three separate Alembic lineages)

**Symptom / trap**: A recurring wrong assumption that every "intelligence"-adjacent table migrates through the `intelligence-migrations` init container. Authoring an `nlp_db` column change there would run it against the wrong physical database (or not at all).

**Reality (verified in each `alembic/env.py`)** — there are THREE independent service Alembic lineages:
- `rag_db` DDL → **rag-chat** (`services/rag-chat/alembic`).
- `nlp_db` DDL → **nlp-pipeline itself** (`services/nlp-pipeline/alembic/env.py`: "This service (S6 NLP Pipeline) ONLY manages nlp_db"). Its `ALEMBIC_ENABLED=false` flag gates ONLY its *intelligence_db* adapter connection — NOT its own nlp_db migrations, which always run.
- `intelligence_db` DDL → **intelligence-migrations** (`INTELLIGENCE_DB_URL`; `target_metadata=None`, SQL-only). S7 knowledge-graph owns no Alembic dir and runs `ALEMBIC_ENABLED=false`.

**Prevention**: Before writing any migration, open the target service's `alembic/env.py` and confirm which physical DB its `ALEMBIC_URL` / `*_DATABASE_URL` binds to. A column added to the wrong lineage is a silent no-op (or a wrong-DB error). This was resolved as OQ-2 in PLAN-0117, whose W2 correctly split the `llm_usage_log` column additions across rag-chat `0010` (rag_db), nlp-pipeline `0023` (nlp_db), and intelligence-migrations `0064` (intelligence_db).

Status: documented guard. References: `services/nlp-pipeline/alembic/env.py`, `services/intelligence-migrations/alembic/env.py`, PLAN-0117 §6.4.

---

## BP-717 — Filtering a pgvector ANN by a column on a JOINED table bypasses the HNSW index (O(bucket) exact scan → client timeout)

**Symptom**: A source-filtered chunk search (`source_types=['sec_edgar']`) returned 0 items to rag-chat ~100% of the time; NEWS answers on the same endpoint intermittently emptied. Server-side the search *completed* (`result_count=25`) but only after ~19s — past rag-chat's `RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS=10` client timeout, so the client got a ReadTimeout and 0 items.

**Root cause**: `source_type` lived only on `document_source_metadata`, joined to the vector table. pgvector's HNSW index (`idx_chunk_emb_hnsw`) can only serve `ORDER BY embedding <=> :q LIMIT k` when the filter is on the vector table itself; a post-join filter forced S6 onto the filter-first EXACT KNN fallback (a `WITH filtered AS MATERIALIZED (…)` CTE that exact-sorts the entire filtered bucket, HNSW structurally unusable). That was sub-second at ~few-k rows, but the R1 filings backfill grew `sec_edgar` to ~30.5k of ~110k ready embeddings, so the exact sort grew to ~19s. EXPLAIN ANALYZE confirmed: `Parallel Seq Scan` + top-N `Sort`, no `idx_chunk_emb_hnsw`.

**Fix (migration 0024 + `ChunkANNRepository` accel path)**:
- Denormalize `source_type` onto `chunk_embeddings` / `section_embeddings` — a partial-index predicate can ONLY reference its own table's columns. Backfilled from `document_source_metadata`; kept current by `BEFORE INSERT` triggers (`trg_chunk_emb_source_type` / `trg_section_emb_source_type`) so all 6+ embedding-write sites stay correct with zero write-path churn.
- Add PARTIAL HNSW indexes `WHERE embedding_status='ready' AND source_type='sec_edgar'` (chunk) and `WHERE source_type='sec_edgar'` (section).
- For a SINGLE allow-listed `source_type` with no entity filter, emit a **LITERAL** `ce.source_type='sec_edgar'` predicate. Postgres `predicate_implied_by` only matches a partial index against a literal or single-element array constant — a bind parameter (`= $1`) or `= ANY($1)` will NOT match and silently falls back to the seq scan. The literal is gated by a `^[a-z0-9_]+$` regex + an allow-list (`chunk_ann_indexed_source_types`) so it is injection-safe.

**Result**: `Index Scan using idx_chunk_emb_hnsw_sec_edgar`, ~20ms (vs 19,416ms), recall@25 = 24-25/25 vs exact ground truth at `hnsw.ef_search` 200-400.

**Environment note**: pgvector here is **0.7.2**, so `hnsw.iterative_scan` (the 0.8+ way to filter *with* the index) is unavailable — the partial-index + literal-predicate approach is the 0.7.x-compatible answer.

**Prevention**: Keep any column you filter a vector ANN by ON the vector table (denormalize if it lives elsewhere, and maintain it with a trigger to cover every write path). Add a partial HNSW index per hot filter value and emit a literal predicate. Watch bucket growth: a "small exact scan" fallback silently becomes a timeout as a corpus grows. Prove recall with a before/after top-k comparison against the exact set — never trade a timeout for empty/garbage results.

Status: FIXED. References: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` (`_accel_source_type`, `_accel_chunk_knn`, `_accel_section_knn`), `services/nlp-pipeline/alembic/versions/0024_denormalize_source_type_onto_embeddings.py`. Related: BP-716 (nlp_db DDL ownership), BUG-3 (ef_search post-filter starvation).
