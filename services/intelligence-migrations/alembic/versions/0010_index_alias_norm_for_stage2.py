"""Add partial index for Stage-2 ticker/PRIMARY_TICKER/ISIN resolver.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-30

PLAN-0057 QA-iter1 F-SEC-03 — closes a DoS-amplification gap.

Background: PLAN-0057 Wave C-3 widened the nlp-pipeline Stage-2 fallback
resolver from ``alias_type='TICKER'`` to ``alias_type IN
('TICKER','PRIMARY_TICKER','ISIN')``. Migration 0001's
``uidx_entity_aliases_normalized`` partial UNIQUE index applies only to
``alias_type='EXACT'`` rows, so the new lookup pattern has no supporting
index and falls back to a sequential scan over ``entity_aliases``.

At ~100k aliases (modest production scale), every NLP article processing
batch (5-30 ticker candidates) triggers one full sequential scan per
candidate, producing ~10x expected DB load on the alias table.

This migration adds a partial composite B-tree index on
``(normalized_alias_text, alias_type)`` filtered to the three alias types
that the widened Stage-2 resolver actually queries. The planner picks
this index for both the single-row lookup and the batched ``IN(...)``
variant.

Idempotent: ``CREATE INDEX IF NOT EXISTS``.
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_entity_aliases_norm_stage2
            ON entity_aliases (normalized_alias_text, alias_type)
            WHERE is_active = true
              AND alias_type IN ('TICKER', 'PRIMARY_TICKER', 'ISIN')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entity_aliases_norm_stage2")
