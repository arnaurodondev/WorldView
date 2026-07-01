"""Add ``cost_source`` + ``user_id`` to nlp_db.llm_usage_log (PLAN-0117 W2, FR-2/FR-3).

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-01

WHY THIS MIGRATION EXISTS (Trustworthy LLM Cost Metering — PRD-0117):
  S6's deep-extraction + relevance-scoring paths write cost rows here. Several
  call sites historically hardcoded ``estimated_cost_usd=0.0`` for PAID
  DeepInfra models (the RC-1 silent-zero bug). PLAN-0117 replaces those with the
  real provider cost and stamps its provenance. To persist that provenance — and
  to attribute cost to an end user where one exists — the nlp_db ledger gains:

    cost_source  VARCHAR(16) NULL   one of: provider | pricematrix | local
    user_id      UUID        NULL   authenticated end user, NULL for pipeline/bg

  NOTE ON OWNERSHIP (R32 / corrected in the PLAN-0117 revise gate): nlp_db DDL
  is owned by S6 nlp-pipeline itself (this alembic lineage; ``env.py``: "S6 ONLY
  manages nlp_db"). The intelligence_db copy of this same column pair is added
  separately by intelligence-migrations 0064 — do NOT route nlp_db DDL there.

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): both columns nullable, no default.
Existing rows read NULL automatically. Zero downtime — no data migration. Follows
the same additive pattern as 0022 (add_fallback_reason_to_llm_usage_log).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
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
