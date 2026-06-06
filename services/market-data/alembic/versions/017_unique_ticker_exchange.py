"""Add unique index on instruments (upper(symbol), exchange) — PLAN-0089 F2 Step 1 (M3).

Revision ID: 017
Revises: 016
Create Date: 2026-05-20

WHY THIS MIGRATION EXISTS:
  PRD-0089 / PLAN-0089 wave F2 enables ticker-first URL routing
  (``/instruments/AAPL`` rather than ``/instruments/{uuid}``) and requires
  a case-insensitive lookup index on ``(symbol, exchange)`` so that the
  gateway resolver path ``resolve_security_id(ticker) → instrument_id``
  returns a deterministic single row.

  The pre-existing ``uq_instruments_symbol_exchange`` UNIQUE constraint
  (from migration 001) enforces uniqueness on ``(symbol, exchange)``
  case-sensitively — e.g. ``('aapl', 'US')`` and ``('AAPL', 'US')`` are
  TWO distinct rows under the existing constraint. F2 normalises every
  ingested ticker to upper-case via ``_normalize_ticker`` in adapters
  (see F2 plan §4.5), so in practice the case-sensitive constraint
  suffices today. This stricter case-insensitive index defends against
  any future ingest path that bypasses the normaliser.

WHAT THIS MIGRATION DOES:
  Creates ``idx_instruments_ticker_exchange_active`` — UNIQUE INDEX on
  ``(upper(symbol), exchange)`` over the ``instruments`` table.

DEVIATION FROM F2 PLAN §2.3:
  The plan body proposes ``WHERE status = 'active'`` so that
  historical/delisted rows could share the same symbol. The
  ``instruments`` table has NO ``status`` column today (verified against
  migrations 001-016 and the live SQLAlchemy ORM model
  ``infrastructure/db/models/instruments.py``). The unique index is
  therefore created UNCONDITIONALLY (no WHERE clause), which is in fact
  strictly stronger than the plan body — every row in ``instruments``
  must have a unique ``(upper(symbol), exchange)`` pair. If/when a
  ``status`` column is added later for delisting/lifecycle support, this
  index can be re-created with the partial predicate via a follow-up
  migration; the upgrade path is a drop + recreate (no data migration
  needed because the partial form is strictly weaker).

  TODO(post-F2): if PRD-0089 future waves introduce a lifecycle column
  on ``instruments`` (e.g. ``status``, ``listed``, ``delisted_at``), open
  a follow-up migration to convert this index to its partial form.

MULTI-CLASS SHARE COMPATIBILITY:
  ``BRK.A`` and ``BRK.B`` remain distinct rows because their ``symbol``
  values differ (``BRK.A`` vs ``BRK.B``). The unique index keys on the
  full ticker string, not just the root.

IDEMPOTENCY:
  Uses ``CREATE UNIQUE INDEX IF NOT EXISTS`` so re-running the migration
  against a DB that already has the index is a no-op.

DOWNGRADE:
  Drops the index. The pre-existing ``uq_instruments_symbol_exchange``
  UNIQUE constraint remains untouched (it was created by migration 001).
"""

from __future__ import annotations

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the case-insensitive unique index on (upper(symbol), exchange)."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_instruments_ticker_exchange_active
          ON instruments (upper(symbol), exchange)
        """
    )


def downgrade() -> None:
    """Drop the case-insensitive unique index."""
    op.execute("DROP INDEX IF EXISTS idx_instruments_ticker_exchange_active")
