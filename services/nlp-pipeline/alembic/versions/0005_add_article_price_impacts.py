"""Add article_price_impacts table for Market-Impact Signal Scoring.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-09

Adds ``article_price_impacts`` which stores retrospective price-impact
labels for processed articles, linking article publication times to
OHLCV price bars for the resolved canonical entity.

Fields:
  - ``id``                     — UUIDv7 primary key (server default gen_random_uuid())
  - ``article_id``             — logical FK to content_store_db.documents.id (UNIQUE)
  - ``entity_id``              — canonical entity whose OHLCV was used
  - ``symbol``                 — ticker symbol
  - ``published_at``           — article publication time UTC
  - ``ohlcv_date``             — OHLCV bar date covering publication time
  - ``price_open``             — opening price NUMERIC(18,8)
  - ``price_close``            — closing price NUMERIC(18,8)
  - ``price_delta_pct``        — (close-open)/open*100 NUMERIC(10,6)
  - ``next_day_delta_pct``     - optional next-day close-to-close delta NUMERIC(10,6)
  - ``max_intraday_range_pct`` — optional (high-low)/open*100 NUMERIC(10,6)
  - ``impact_score``           — normalised 0.0-1.0 NUMERIC(6,4)
  - ``computed_at``            — when computed TIMESTAMPTZ DEFAULT now()

Indexes:
  - UNIQUE on article_id (implicit from inline UNIQUE constraint)
  - ix_api_entity_date on (entity_id, ohlcv_date) — batch lookups by entity
  - ix_api_impact_score_partial on (impact_score DESC) WHERE impact_score > 0.3

PRD reference: §6.4 (Database Changes)
ORM model: nlp_pipeline.infrastructure.nlp_db.models.ArticlePriceImpactModel (added Wave A-2)
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        "CREATE INDEX ix_api_impact_score_partial ON article_price_impacts "
        "(impact_score DESC) WHERE impact_score > 0.3"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_impact_score_partial")
    op.execute("DROP INDEX IF EXISTS ix_api_entity_date")
    op.execute("DROP TABLE IF EXISTS article_price_impacts")
