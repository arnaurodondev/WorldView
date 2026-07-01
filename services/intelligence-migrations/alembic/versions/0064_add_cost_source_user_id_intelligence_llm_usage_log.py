"""Add ``cost_source`` + ``user_id`` to intelligence_db.llm_usage_log (PLAN-0117 W2, FR-2/FR-3).

Revision ID: 0064
Revises: 0063
Create Date: 2026-07-01

WHY THIS MIGRATION EXISTS (Trustworthy LLM Cost Metering — PRD-0117):
  The knowledge-graph service (S7) logs every enrichment/summary LLM call into
  intelligence_db.llm_usage_log. S7 owns NO alembic lineage (ALEMBIC_ENABLED=false
  for intelligence_db); intelligence-migrations is the sole DDL owner (R24/R32).
  We add the SAME two audit columns here that rag-chat 0010 and nlp-pipeline 0023
  add to their ledgers, so cost provenance + user attribution are consistent
  across ALL THREE physical llm_usage_log tables:

    cost_source  VARCHAR(16) NULL   one of: provider | pricematrix | local
    user_id      UUID        NULL   authenticated end user, NULL for pipeline/bg

  S7's DeepInfra enrichment writes will prefer the provider-returned cost
  (``cost_source='provider'``); Gemini falls back to the matrix
  (``pricematrix``); Ollama stays legitimately free (``local``).

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): both columns nullable, no default.
Existing rows read NULL automatically. Plain column add (fail-loud, unlike AGE
DDL) — a failure surfaces as a migration error. Follows the additive pattern of
0058 (add_fallback_reason_to_llm_usage_log).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage_log",
        sa.Column("cost_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "llm_usage_log",
        sa.Column("user_id", sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_usage_log", "user_id")
    op.drop_column("llm_usage_log", "cost_source")
