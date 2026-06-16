"""Add ``fallback_reason`` to nlp_db.llm_usage_log (Task #36).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-15

WHY THIS MIGRATION EXISTS (extraction 429-fallback audit):
  After a platform outage, a backlog saturated the PRIMARY deep-extraction model
  (Qwen/Qwen3-235B-A22B-Instruct-2507 on DeepInfra). Articles hit the consumer's
  message_processing_timeout and were dead-lettered. Task #36 makes the
  DeepSeekExtractionAdapter fall back to a SECONDARY model (deepseek-ai/
  DeepSeek-V4-Flash) on HTTP 429 / persistent timeout.

  To AUDIT when/why the secondary served calls, the deep-extraction usage-log row
  now records the ACTUAL serving model (``model_id``) PLUS this new column:

    fallback_reason  TEXT NULL
                     One of: none | rate_limit | timeout | server_error.
                     NULL for callers that don't emit it (non-extraction rows).

  This makes the operator query work:
    SELECT model_id, fallback_reason, count(*)
    FROM llm_usage_log GROUP BY 1, 2;

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): new nullable column, no default
needed (BP-126 only requires server_default on NOT NULL columns). Existing rows
get NULL automatically. Zero downtime — no data migration, no row rewrite.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage_log",
        sa.Column("fallback_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage_log", "fallback_reason")
