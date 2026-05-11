"""Add sentiment + impact_score columns to document_source_metadata (PLAN-0050 Wave E T-E-5-01).

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-29

The NLP pipeline's ArticleRelevanceScoringWorker enriches articles with two
new signals that the frontend needs for the News-tab sentiment pill and impact
pill (PRD-0050 Wave E):

  sentiment     — categorical: positive | negative | neutral | mixed (nullable).
                  Null until the worker processes the article or the article is
                  LIGHT-tier (skipped for LLM scoring).

  impact_score  - float 0.0-1.0 convenience column aggregated from
                  article_impact_windows.  Duplicates MAX(day_t0, day_t1) but
                  stored here so the news query CTE can avoid an extra JOIN.
                  Nullable until price-impact windows are computed.

Forward-compatibility (BP-126):
  - Both columns are nullable → no server_default needed → no table rewrite.
  - Adding fields with defaults is always safe; removing/renaming is forbidden.

Zero-downtime: nullable ADD COLUMN; index is partial for populated rows only.

Downgrade:
  - DROP INDEX + DROP COLUMN (safe; no data loss beyond the enrichment values).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add sentiment enum column — TEXT with CHECK constraint.
    #    WHY TEXT not ENUM type: Postgres ENUM types require CREATE TYPE which is harder
    #    to roll back safely. A TEXT CHECK constraint achieves the same validity guarantee
    #    and is simpler to migrate if new values are added later (just extend the check).
    op.add_column(
        "document_source_metadata",
        sa.Column(
            "sentiment",
            sa.Text(),
            nullable=True,
            comment="Article sentiment: positive | negative | neutral | mixed; null until scored",
        ),
    )
    # WHY sa.text for CHECK: op.add_column doesn't accept sa.CheckConstraint natively;
    # using raw DDL is the canonical Alembic pattern for complex constraints.
    op.execute("""
        ALTER TABLE document_source_metadata
        ADD CONSTRAINT chk_dsm_sentiment
        CHECK (sentiment IN ('positive', 'negative', 'neutral', 'mixed') OR sentiment IS NULL)
    """)

    # 2. Add impact_score convenience column - 0.0-1.0 float, nullable.
    #    WHY NUMERIC(6,4): matches the precision used in article_impact_windows.impact_score.
    #    Avoids floating-point rounding surprises (Decimal 0.xxxx stored losslessly).
    op.add_column(
        "document_source_metadata",
        sa.Column(
            "impact_score",
            sa.Numeric(6, 4),
            nullable=True,
            comment="Convenience copy of MAX(day_t0, day_t1) from article_impact_windows; null until computed",
        ),
    )

    # 3. Partial index: only index rows that have been scored (sentiment IS NOT NULL).
    #    WHY partial: unscored rows (null) don't need to be in the index — the API
    #    never filters by sentiment = NULL. Keeps index small during the initial rollout.
    op.execute("""
        CREATE INDEX idx_dsm_sentiment
        ON document_source_metadata (sentiment, published_at DESC)
        WHERE sentiment IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_dsm_sentiment")
    op.execute("""
        ALTER TABLE document_source_metadata
        DROP CONSTRAINT IF EXISTS chk_dsm_sentiment
    """)
    op.drop_column("document_source_metadata", "impact_score")
    op.drop_column("document_source_metadata", "sentiment")
