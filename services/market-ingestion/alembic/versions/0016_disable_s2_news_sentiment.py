"""Disable S2 news_sentiment polling policies (moving to S4).

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-06

PLAN-0106 Wave C-0 — Disable S2 News Sentiment.

Rationale
---------
News-sentiment ingestion is moving to the content-ingestion service (S4)
which is better suited for managing article-level NLP pipelines.  S2
(market-ingestion) should not duplicate this work.

This migration bulk-disables all ``dataset_type='news_sentiment'`` polling
policies for provider ``eodhd`` so they stop being scheduled.  The policies
are preserved (not deleted) for historical audit purposes and to support a
clean rollback path.

Forward-compat (R5):
    Only an UPDATE — no schema changes.  Rollback re-enables the same rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'news_sentiment'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'news_sentiment'"
        )
    )
