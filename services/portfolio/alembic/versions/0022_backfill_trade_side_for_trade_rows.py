"""Backfill trade_side for TRADE rows persisted with NULL (data-only).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-10

2026-06-10 frontend-enhancement sprint follow-up: PLAN-0108 (migration 0021)
added ``trade_side`` to the table and the domain entity, but
``SqlAlchemyTransactionRepository.save()`` never wrote the column — every
TRADE recorded through the API landed with ``trade_side = NULL``. Because
``Transaction.__post_init__`` enforces "trade_side required for TRADE",
hydrating such a row raised ``ValueError`` and 500'd any read that touched
it (realized-pnl, deep transaction pages, the new TWR endpoint).

The code fix (same change set) persists the column going forward and infers
the side from ``direction`` for legacy rows at hydration time. This
migration repairs the stored data so the read-time inference (and its
warning log) stops firing:

    INFLOW  (securities entered the book)  → BUY
    OUTFLOW (securities left the book)     → SELL

— the exact mapping RecordTransactionUseCase uses on the write path.

Data-only: no DDL, idempotent (WHERE trade_side IS NULL), trivially safe to
re-run. Downgrade restores NULL (the pre-fix state) for rows this migration
touched is NOT possible to distinguish, so downgrade is a no-op — the
backfilled values are correct either way and harmless under revision 0021.
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE transactions
        SET trade_side = CASE direction WHEN 'INFLOW' THEN 'BUY' ELSE 'SELL' END
        WHERE transaction_type = 'TRADE' AND trade_side IS NULL
        """,
    )


def downgrade() -> None:
    # No-op: the backfilled values are semantically correct under the 0021
    # schema (nullable column, CHECK allows BUY/SELL). Reverting them to NULL
    # would re-introduce the hydration crash on older code.
    pass
