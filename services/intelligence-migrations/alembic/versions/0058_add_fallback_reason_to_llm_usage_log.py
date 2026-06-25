"""Add ``fallback_reason`` to intelligence_db.llm_usage_log (Task #36).

Revision ID: 0058
Revises: 0057
Create Date: 2026-06-15

WHY THIS MIGRATION EXISTS (extraction 429-fallback audit):
  Task #36 hardens the deep-extraction LLM path so a saturated PRIMARY model
  (Qwen/Qwen3-235B-A22B-Instruct-2507) no longer dead-letters articles: the
  shared DeepSeekExtractionAdapter now retries transient failures and, on HTTP 429
  / persistent timeout, falls back to a SECONDARY model (deepseek-ai/
  DeepSeek-V4-Flash) carrying the SAME extraction prompt + JSON response_format.

  The extraction usage row records the ACTUAL serving model PLUS a
  ``fallback_reason`` tag. The nlp-pipeline deep-extraction path writes to
  nlp_db.llm_usage_log (migration 0022 there). The knowledge-graph service also
  owns an ``llm_usage_log`` table in intelligence_db (extended in this repo's
  revision 0006) for ITS LLM calls (enrichment/summary). We add the SAME column
  here so the audit column is consistent across BOTH usage-log tables and any
  KG-side extraction path that adopts the adapter records it too.

    fallback_reason  TEXT NULL
                     One of: none | rate_limit | timeout | server_error.
                     NULL for callers that don't emit it.

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): new nullable column. Existing rows
get NULL automatically. Zero downtime. Plain column add — unlike BP-688's AGE DDL
this cannot be silently swallowed; a failure here will surface as a migration
error (fail-loud).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage_log",
        sa.Column("fallback_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage_log", "fallback_reason")
