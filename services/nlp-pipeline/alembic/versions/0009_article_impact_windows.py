"""Replace article_price_impacts with article_impact_windows (PRD-0026 §6.4, §12).

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-22

This migration implements the multi-window price-impact table design from
PRD-0026.  Instead of a single day_t0 impact row per article, the new table
stores one row per (article_id, entity_id, window_type), enabling day_t0 /
day_t1 / day_t2 / day_t5 windows and future intraday windows.

Operations (in order):
  1. CREATE TABLE article_impact_windows  — new multi-window table
  2. INSERT ...  — migrate existing article_price_impacts rows as day_t0
     (WHERE price_open > 0: excludes zero-sentinel rows from ArticlePriceImpact.zero())
  3. DROP TABLE article_price_impacts     — remove old single-window table
  4. ALTER TABLE document_source_metadata — add llm_relevance_score + llm_scored_at
  5. CREATE indexes (unique + query-plan)
  6. CREATE index on routing_decisions(doc_id) — needed for JOIN performance

Indexes created:
  idx_article_impact_windows_unique   — UNIQUE (article_id, entity_id, window_type)
  idx_article_impact_windows_entity   — (entity_id, window_type, published_at DESC)
  idx_article_impact_windows_day_t0   — PARTIAL on window_type='day_t0' (impact_score DESC)
  idx_article_impact_windows_article  — (article_id) for JOIN from document_source_metadata
  idx_dsm_published_at                — document_source_metadata (published_at DESC)
  idx_routing_decisions_doc_id        — routing_decisions (doc_id)

Zero-downtime: new table created before old table dropped; both new columns on
document_source_metadata are nullable (no server_default needed, BP-126).

Downgrade notes:
  - Data migrated to article_impact_windows is NOT reversed (one-way migration).
  - Downgrade re-creates the empty article_price_impacts schema from migration 0005.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create article_impact_windows ─────────────────────────────────────
    op.execute("""
        CREATE TABLE article_impact_windows (
            id                   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            article_id           UUID          NOT NULL,
            entity_id            UUID          NOT NULL,
            symbol               TEXT          NOT NULL,
            published_at         TIMESTAMPTZ   NOT NULL,
            window_type          VARCHAR(20)   NOT NULL,
            window_start         TIMESTAMPTZ   NOT NULL,
            window_end           TIMESTAMPTZ   NOT NULL,
            price_start          NUMERIC(18,8) NOT NULL,
            price_end            NUMERIC(18,8) NOT NULL,
            delta_pct            NUMERIC(10,6) NOT NULL,
            high_pct             NUMERIC(10,6),
            low_pct              NUMERIC(10,6),
            volume               NUMERIC(18,2),
            impact_score         NUMERIC(6,4)  NOT NULL,
            normalisation_cap_pct NUMERIC(6,2) NOT NULL,
            data_quality         VARCHAR(20)   NOT NULL DEFAULT 'daily_proxy',
            computed_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
        )
    """)

    # ── 2. Migrate existing article_price_impacts rows as day_t0 windows ─────
    # WHERE price_open > 0: excludes ArticlePriceImpact.zero() sentinel rows
    # (zero-sentinel rows have price_open=0 and represent "OHLCV unavailable",
    #  not a valid measurement — see PRD-0026 §12 and §6.4 migration notes).
    op.execute("""
        INSERT INTO article_impact_windows (
            id,
            article_id, entity_id, symbol, published_at,
            window_type, window_start, window_end,
            price_start, price_end, delta_pct,
            high_pct, low_pct, volume,
            impact_score, normalisation_cap_pct, data_quality, computed_at
        )
        SELECT
            gen_random_uuid(),
            article_id, entity_id, symbol, published_at,
            'day_t0',
            DATE_TRUNC('day', published_at)::TIMESTAMPTZ,
            (DATE_TRUNC('day', published_at) + INTERVAL '1 day')::TIMESTAMPTZ,
            price_open, price_close, price_delta_pct,
            max_intraday_range_pct, NULL, NULL,
            impact_score, 5.0, 'daily_proxy', computed_at
        FROM article_price_impacts
        WHERE price_open > 0
    """)

    # ── 3. Drop old single-window table ───────────────────────────────────────
    op.execute("DROP TABLE article_price_impacts")

    # ── 4. Add LLM scoring columns to document_source_metadata ───────────────
    # Both nullable: no server_default needed (BP-126: only NOT NULL cols need it)
    op.add_column(
        "document_source_metadata",
        sa.Column("llm_relevance_score", sa.Numeric(6, 4), nullable=True),
    )
    op.add_column(
        "document_source_metadata",
        sa.Column("llm_scored_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 5. Create indexes on article_impact_windows ───────────────────────────

    # UNIQUE constraint — required for ON CONFLICT (article_id, entity_id, window_type)
    op.execute("""
        CREATE UNIQUE INDEX idx_article_impact_windows_unique
        ON article_impact_windows (article_id, entity_id, window_type)
    """)

    # Entity-scoped queries: find all windows for a given entity+window_type
    op.execute("""
        CREATE INDEX idx_article_impact_windows_entity
        ON article_impact_windows (entity_id, window_type, published_at DESC)
    """)

    # Global top-news queries: find highest day_t0 impact articles
    op.execute("""
        CREATE INDEX idx_article_impact_windows_day_t0
        ON article_impact_windows (impact_score DESC)
        WHERE window_type = 'day_t0'
    """)

    # JOIN from document_source_metadata side
    op.execute("""
        CREATE INDEX idx_article_impact_windows_article
        ON article_impact_windows (article_id)
    """)

    # ── 6. Create index on document_source_metadata(published_at DESC) ────────
    # Needed by GetTopNewsUseCase time-window filter (PRD-0026 §6.4)
    op.execute("""
        CREATE INDEX idx_dsm_published_at
        ON document_source_metadata (published_at DESC)
    """)

    # ── 7. Create index on routing_decisions(doc_id) ──────────────────────────
    # routing_decisions only has PK on decision_id; the JOIN on doc_id is a seq scan
    # without this index (PRD-0026 §6.4)
    op.execute("""
        CREATE INDEX idx_routing_decisions_doc_id
        ON routing_decisions (doc_id)
    """)


def downgrade() -> None:
    # Drop all new indexes first
    op.execute("DROP INDEX IF EXISTS idx_routing_decisions_doc_id")
    op.execute("DROP INDEX IF EXISTS idx_dsm_published_at")
    op.execute("DROP INDEX IF EXISTS idx_article_impact_windows_article")
    op.execute("DROP INDEX IF EXISTS idx_article_impact_windows_day_t0")
    op.execute("DROP INDEX IF EXISTS idx_article_impact_windows_entity")
    op.execute("DROP INDEX IF EXISTS idx_article_impact_windows_unique")

    # Remove new columns from document_source_metadata
    op.drop_column("document_source_metadata", "llm_scored_at")
    op.drop_column("document_source_metadata", "llm_relevance_score")

    # Drop new table (data is NOT restored — one-way migration)
    op.execute("DROP TABLE IF EXISTS article_impact_windows")

    # Re-create article_price_impacts with the original 0005 schema (empty)
    op.execute("""
        CREATE TABLE article_price_impacts (
            id                     UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            article_id             UUID          UNIQUE NOT NULL,
            entity_id              UUID          NOT NULL,
            symbol                 TEXT          NOT NULL,
            published_at           TIMESTAMPTZ   NOT NULL,
            ohlcv_date             DATE          NOT NULL,
            price_open             NUMERIC(18,8) NOT NULL,
            price_close            NUMERIC(18,8) NOT NULL,
            price_delta_pct        NUMERIC(10,6) NOT NULL,
            next_day_delta_pct     NUMERIC(10,6),
            max_intraday_range_pct NUMERIC(10,6),
            impact_score           NUMERIC(6,4)  NOT NULL,
            computed_at            TIMESTAMPTZ   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_api_entity_date ON article_price_impacts (entity_id, ohlcv_date)")
    op.execute(
        "CREATE INDEX ix_api_impact_score_partial ON article_price_impacts (impact_score DESC) WHERE impact_score > 0.3"
    )
