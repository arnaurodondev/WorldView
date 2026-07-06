"""Denormalize ``source_type`` onto embeddings + partial HNSW index (S6 ANN latency fix).

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-05

WHY THIS MIGRATION EXISTS (S6 chunk-search timeout on the grown sec_edgar corpus):
  The ``POST /api/v1/search/chunks`` ANN path filters by ``source_type``, which
  lives on ``document_source_metadata`` (a SEPARATE table) and was applied as a
  POST-JOIN filter. Because the filter column is not on the vector table, the
  pgvector HNSW index (``idx_chunk_emb_hnsw``) is BYPASSED for a source-filtered
  query: the repository falls back to a filter-first EXACT KNN (a MATERIALIZED
  CTE that exact-sorts the whole filtered bucket). That was "a few thousand rows
  = sub-millisecond" when the corpus was ~66k, but the R1 filings backfill grew
  ``sec_edgar`` to ~30.5k of ~110k ready embeddings, so the exact sort now takes
  ~19 s server-side — PAST rag-chat's ``RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS=10``
  client timeout → ``get_filings`` returns 0 items ~100% of the time (and the
  same endpoint intermittently empties NEWS answers).

  EXPLAIN ANALYZE (nlp_db, source_types=['sec_edgar'], top_k=25):
    BEFORE: Execution Time ~= 19_400 ms — Parallel Seq Scan + top-N sort, HNSW unused.
    AFTER : Execution Time ~=     20 ms — Index Scan using idx_chunk_emb_hnsw_sec_edgar.
    Recall@25 vs exact ground truth: 24-25 / 25 at hnsw.ef_search=200 (ANN standard;
    the current path returns the exact set but delivers 0 to the client on timeout).

WHAT THIS DOES:
  1. Adds ``source_type TEXT NULL`` to ``chunk_embeddings`` and ``section_embeddings``
     (denormalized from ``document_source_metadata.source_type`` via doc_id). The
     partial HNSW index MUST reference a column on the vector table itself — a
     partial-index predicate cannot reference a joined table — so the filter
     column has to live here, not stay on ``document_source_metadata``.
  2. Backfills the new column for all existing rows from ``document_source_metadata``.
  3. Installs ``BEFORE INSERT`` triggers that keep the column current for every
     future insert (there are 6+ embedding-insert sites — article consumer,
     retry worker, backfill workers — and threading source_type through all of
     them is brittle; a trigger is the single, write-path-agnostic source of
     truth. The trigger only fires when the caller did not set the column, so
     explicit writes / tests can still override it).
  4. Creates PARTIAL HNSW indexes for the ``sec_edgar`` bucket on both tables, so
     a single-source ``source_type='sec_edgar'`` ANN query is served by the index
     (``ORDER BY embedding <=> :vec`` + ``LIMIT``) instead of an exact seq-scan
     sort. The repository emits a validated LITERAL ``ce.source_type='sec_edgar'``
     predicate on the accelerated path so Postgres ``predicate_implied_by`` matches
     the partial index. Extending to another bucket = 1 partial index here + 1
     entry in ``ChunkANNRepository._INDEXED_SOURCE_TYPES``.

OWNERSHIP (R32, mirrors 0023's header): nlp_db DDL is owned by S6 nlp-pipeline
itself (this alembic lineage; ``env.py``: "S6 ONLY manages nlp_db"). This is NOT
an intelligence_db change — do NOT route it to intelligence-migrations.

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): both columns nullable, no default;
existing readers ignore the column. The old exact-KNN path stays as the fallback
for any non-accelerated filter shape (multi-source, entity filters, un-indexed
sources), so recall is preserved everywhere. Fully reversible (see downgrade()).
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


# The buckets that get a dedicated partial HNSW index. Keep in lock-step with
# ``ChunkANNRepository._INDEXED_SOURCE_TYPES``. sec_edgar is the reported break
# (get_filings). Add a new value in BOTH places to accelerate another bucket.
# Values are hardcoded (never user input) so inlining them as SQL literals below
# is injection-safe.
_INDEXED_SOURCE_TYPES = ("sec_edgar",)


def upgrade() -> None:
    # ── 1. Denormalized column (nullable, no default → instant metadata-only add) ─
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN source_type TEXT")
    op.execute("ALTER TABLE section_embeddings ADD COLUMN source_type TEXT")

    # Keep the ENTIRE HNSW graph in backend-local memory during the bulk rebuild.
    # 512MB is too small for ~110k x 1024-dim vectors (~500MB of vectors alone) →
    # the graph spills to disk and the single-threaded build decelerates to a crawl
    # (~0.5%/min). 2GB holds it in RAM → minutes not tens-of-minutes. Backend-local
    # (not shared), so it does NOT hit /dev/shm; the host has ample free memory.
    # Transaction-local — reverts on commit.
    op.execute("SET LOCAL maintenance_work_mem = '2GB'")

    # The one-time backfill (~110k-row UPDATE that churns the existing HNSW index)
    # plus the partial-index CREATE exceed nlp_db's 10min ``statement_timeout`` on a
    # grown/loaded corpus → the statement is cancelled and the migrate container
    # restart-loops without ever committing. Disable the timeout for THIS migration
    # transaction only (transaction-local; reverts on commit). Bounded operations,
    # run once under supervision.
    op.execute("SET LOCAL statement_timeout = 0")

    # Build the HNSW indexes SINGLE-THREADED. A parallel maintenance build spins up
    # worker processes that allocate a shared-memory segment sized ~maintenance_work_mem
    # (~512MB) in the container's /dev/shm — which Docker defaults to 64MB — yielding
    # ``DiskFullError: could not resize shared memory segment ... No space left on
    # device``. A non-parallel build uses backend-LOCAL memory instead. (Belt-and-braces
    # with any DB-level ALTER; transaction-local, reverts on commit.)
    op.execute("SET LOCAL max_parallel_maintenance_workers = 0")

    # ── 1b. Drop the GLOBAL HNSW indexes BEFORE the backfill ──────────────────
    # The backfill UPDATE rewrites every row (non-HOT: source_type is a fresh
    # column and the pages are packed), which forces a per-row HNSW graph insert
    # into idx_chunk_emb_hnsw / idx_section_emb_hnsw. At ~110k rows that per-row
    # churn is ~68ms/row → ~110 min and pathological. Dropping the graph indexes
    # first makes the backfill a plain heap UPDATE (minutes), then we rebuild the
    # graphs ONCE in bulk below (far cheaper than 110k incremental inserts). All
    # inside the migration txn, so a failure rolls the DROP back and restores them.
    op.execute("DROP INDEX IF EXISTS idx_chunk_emb_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_section_emb_hnsw")

    # ── 2. Backfill from document_source_metadata via doc_id ──────────────────
    # chunk_embeddings → chunks(doc_id) → document_source_metadata(source_type)
    op.execute(
        """
        UPDATE chunk_embeddings ce
        SET source_type = dsm.source_type
        FROM chunks c
        JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id
        WHERE ce.chunk_id = c.chunk_id
          AND ce.source_type IS DISTINCT FROM dsm.source_type
        """
    )
    # section_embeddings → sections(doc_id) → document_source_metadata(source_type)
    op.execute(
        """
        UPDATE section_embeddings se
        SET source_type = dsm.source_type
        FROM sections s
        JOIN document_source_metadata dsm ON dsm.doc_id = s.doc_id
        WHERE se.section_id = s.section_id
          AND se.source_type IS DISTINCT FROM dsm.source_type
        """
    )

    # ── 2b. Rebuild the GLOBAL HNSW indexes ONCE in bulk (dropped in 1b) ───────
    # Bulk build over the whole corpus is far cheaper than the per-row churn the
    # backfill would otherwise have caused. Exact defs mirror 0001 (opclass +
    # predicate). maintenance_work_mem was raised above for this build.
    op.execute(
        """
        CREATE INDEX idx_chunk_emb_hnsw ON chunk_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_section_emb_hnsw ON section_embeddings
            USING hnsw (embedding vector_cosine_ops)
        """
    )

    # ── 3. BEFORE INSERT triggers keep the column current on every write path ──
    op.execute(
        """
        CREATE OR REPLACE FUNCTION nlp_set_chunk_embedding_source_type()
        RETURNS trigger AS $$
        BEGIN
            -- Only auto-fill when the caller did not set it explicitly, so
            -- backfills / tests / future explicit writers can override.
            IF NEW.source_type IS NULL THEN
                SELECT dsm.source_type INTO NEW.source_type
                FROM chunks c
                JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id
                WHERE c.chunk_id = NEW.chunk_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION nlp_set_section_embedding_source_type()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.source_type IS NULL THEN
                SELECT dsm.source_type INTO NEW.source_type
                FROM sections s
                JOIN document_source_metadata dsm ON dsm.doc_id = s.doc_id
                WHERE s.section_id = NEW.section_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_chunk_emb_source_type
            BEFORE INSERT ON chunk_embeddings
            FOR EACH ROW EXECUTE FUNCTION nlp_set_chunk_embedding_source_type()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_section_emb_source_type
            BEFORE INSERT ON section_embeddings
            FOR EACH ROW EXECUTE FUNCTION nlp_set_section_embedding_source_type()
        """
    )

    # ── 4. Partial HNSW indexes per indexed bucket ────────────────────────────
    # chunk_embeddings mirrors the existing idx_chunk_emb_hnsw predicate
    # (embedding_status='ready') plus the source_type literal. section_embeddings
    # has no embedding_status column (see 0001), so the predicate is source_type only.
    # Plain (non-CONCURRENT) CREATE INDEX: runs inside the migration transaction —
    # CONCURRENTLY is intentionally avoided here (BP-393).
    for src in _INDEXED_SOURCE_TYPES:
        op.execute(
            f"""
            CREATE INDEX idx_chunk_emb_hnsw_{src} ON chunk_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WHERE embedding_status = 'ready' AND source_type = '{src}'
            """
        )
        op.execute(
            f"""
            CREATE INDEX idx_section_emb_hnsw_{src} ON section_embeddings
                USING hnsw (embedding vector_cosine_ops)
                WHERE source_type = '{src}'
            """
        )


def downgrade() -> None:
    for src in _INDEXED_SOURCE_TYPES:
        op.execute(f"DROP INDEX IF EXISTS idx_section_emb_hnsw_{src}")
        op.execute(f"DROP INDEX IF EXISTS idx_chunk_emb_hnsw_{src}")

    op.execute("DROP TRIGGER IF EXISTS trg_section_emb_source_type ON section_embeddings")
    op.execute("DROP TRIGGER IF EXISTS trg_chunk_emb_source_type ON chunk_embeddings")
    op.execute("DROP FUNCTION IF EXISTS nlp_set_section_embedding_source_type()")
    op.execute("DROP FUNCTION IF EXISTS nlp_set_chunk_embedding_source_type()")

    op.execute("ALTER TABLE section_embeddings DROP COLUMN IF EXISTS source_type")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS source_type")
