"""Add ``cost_source`` + ``user_id`` to rag_db.llm_usage_log (PLAN-0117 W2, FR-2/FR-3).

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-01

WHY THIS MIGRATION EXISTS (Trustworthy LLM Cost Metering — PRD-0117):
  The ``llm_usage_log`` ledger records every LLM call's token counts and
  ``estimated_cost_usd`` but cannot answer two audit questions:

    1. WHERE did the cost figure come from? DeepInfra now returns an
       authoritative ``usage.estimated_cost`` (``cost_source='provider'``);
       when it doesn't, we fall back to the local price matrix
       (``cost_source='pricematrix'``); Ollama/GLiNER calls are legitimately
       free (``cost_source='local'``). Without this provenance a $0 row is
       indistinguishable from a silent-zero regression (RC-1/RC-2/RC-3).

    2. WHICH end user drove the spend? Chat capabilities run in an
       authenticated user context, so we can now attribute cost per user.

  This migration adds the two audit columns to the rag-chat-owned ledger:

    cost_source  VARCHAR(16) NULL   one of: provider | pricematrix | local
    user_id      UUID        NULL   authenticated end user, NULL for system/bg

ADDITIVE / FORWARD-COMPATIBLE (Hard Rule 11): both columns are nullable with
no server_default. Pre-0117 rows read NULL automatically — a NULL
``cost_source`` unambiguously means "written before provenance tracking
existed", never a regression. Zero downtime; no data migration; no row rewrite.

WHY raw SQL via ``op.execute`` (not ``op.add_column``): the rag-chat DDL
alignment test (``tests/unit/infrastructure/test_ddl_alignment.py``) parses
migration files with a regex over ``CREATE TABLE`` / ``ALTER TABLE``
statements. Migrations 0005/0009 established this convention for rag_db —
follow it so the DDL guard sees the columns.

WHY ``IF NOT EXISTS`` / ``IF EXISTS``: makes the migration idempotent against a
partially-applied replay (BP-019) without changing the forward-compat contract.
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Raw SQL form — see module docstring for why we avoid op.add_column here.
    op.execute("ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS cost_source VARCHAR(16) NULL")
    op.execute("ALTER TABLE llm_usage_log ADD COLUMN IF NOT EXISTS user_id UUID NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE llm_usage_log DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE llm_usage_log DROP COLUMN IF EXISTS cost_source")
