"""Add tsv_english + tsv_simple GENERATED columns + GIN indexes to chunks (PLAN-0063 W5-2 / FR-T1-2).

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-06

PLAN-0063 §0-bis.0 v2 lock L7-L8: lexical retrieval substrate for hybrid search.

Adds two GENERATED tsvector columns on ``chunks`` plus matching GIN indexes:

  * ``tsv_english`` — weighted tsvector using the ``english`` config (with stemming).
    Weights:
      A — title_denorm        (article title; strongest signal)
      B — section_heading_denorm (section heading, e.g. "Item 1A. Risk Factors")
      C — RESERVED for W5-7 contextual_description (do NOT add now)
      D — chunk_text          (chunk body; weakest weight)

  * ``tsv_simple`` — unweighted tsvector using the ``simple`` config (no stemming,
    preserves identifiers like ``PLAN-0063`` or ``AAPL`` that english stemming
    would normalise away).

Three ordinary text columns are added so the chunk-writer can populate weights
A/B/D at insert time:
  * ``title_denorm``           — populated from doc.title
  * ``section_heading_denorm`` — populated from section.title
  * ``chunk_text``             — populated from Chunk.text (the actual body)

WHY ``chunk_text`` is in the row even though the body also lives in MinIO:
the existing ``chunks.chunk_text_key`` column holds a MinIO OBJECT KEY
(e.g. ``nlp-pipeline/chunk-text/<uuid>/<uuid>/body/v1.txt``), not the body.
Pointing the GENERATED tsvectors at ``chunk_text_key`` would tokenize file
paths instead of content (BP-NEW-CHUNK-TEXT). MinIO is retained for full-text
fetch on display; ``chunk_text`` is the denormalised copy purely for FTS.

These columns remain NULL for any pre-existing rows; the dev environment
recreates from scratch so no backfill is necessary.

Forward-compatibility / storage budget:
  Median chunk_text ~3 KB; p99 ~8 KB.  Each stored tsvector is roughly 10-20%
  the size of its source text, so the two GENERATED columns add ~0.6-1.6 KB
  per row on average.  At 1 M rows the GIN index for tsv_english is typically
  50-200 MB depending on vocabulary diversity; tsv_simple is somewhat smaller.
  For 10 M rows, tune autovacuum: set ``autovacuum_vacuum_scale_factor=0.01``
  and ``autovacuum_analyze_scale_factor=0.005`` on the chunks table to avoid
  bloat.  Retirement path: PLAN-0064 W6 may render the GIN index redundant if
  full-text search migrates to a dedicated search layer (e.g. Elasticsearch or
  Typesense); drop the two GIN indexes and the GENERATED columns at that point.

Forward-compatibility:
  * All ``ALTER TABLE`` use ``IF NOT EXISTS`` / ``IF EXISTS``.
  * Indexes are unique-named (``ix_chunks_tsv_english_gin`` / ``ix_chunks_tsv_simple_gin``).
  * Downgrade reverses in safe order: drop indexes → drop GENERATED columns →
    drop the denorm text columns. The GENERATED columns reference the denorm
    columns via the expression — Postgres rejects dropping a referenced column
    if the GENERATED column is still present, so order matters.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Plain TEXT columns the chunk-writer populates per row ────────────
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS title_denorm TEXT")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS section_heading_denorm TEXT")
    # chunk_text is the denormalised body for FTS only. MinIO retains the
    # canonical copy via chunk_text_key; this column exists so the GENERATED
    # tsvectors below have actual content to tokenize. See BP-NEW-CHUNK-TEXT.
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_text TEXT")

    # ── 2. GENERATED tsvector columns (computed by Postgres from the row) ──
    # tsv_english — weighted A/B/D; weight C reserved for W5-7 contextual_description.
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN IF NOT EXISTS tsv_english tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title_denorm, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(section_heading_denorm, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(chunk_text, '')), 'D')
        ) STORED
        """
    )

    # tsv_simple — no stemming, preserves identifier tokens (e.g. ticker symbols,
    # plan IDs). Used by the rare-token analyzer in W5-3 + identifier searches.
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN IF NOT EXISTS tsv_simple tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(chunk_text, ''))
        ) STORED
        """
    )

    # ── 3. GIN indexes ───────────────────────────────────────────────────────
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_tsv_english_gin ON chunks USING GIN (tsv_english)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_tsv_simple_gin ON chunks USING GIN (tsv_simple)")


def downgrade() -> None:
    # Reverse order: indexes first, then GENERATED columns, then the underlying
    # text columns the GENERATED expressions referenced. Postgres refuses to drop
    # a column that a GENERATED column still depends on, so this order is
    # mandatory — do not "simplify" it.
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_simple_gin")
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_english_gin")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_simple")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv_english")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS chunk_text")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS section_heading_denorm")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS title_denorm")
