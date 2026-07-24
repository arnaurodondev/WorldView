"""Prevent duplicate placeholder-exchange rows per symbol.

Revision ID: 047
Revises: 046
Create Date: 2026-07-24

WHY THIS MIGRATION EXISTS:

  Migration 046 merged duplicate ``instruments`` rows caused by the
  NFLX-duplicate-instrument incident: ``uq_instruments_symbol_exchange`` is
  keyed on the EXACT ``(symbol, exchange)`` pair, so an ``exchange=''``
  placeholder row and a real-exchange row for the same symbol never collide
  on that constraint — both inserts "succeed" as distinct rows.

  The primary fix is application-level (``_instrument_dedup.py``, used by
  ``ohlcv_consumer``/``quotes_consumer``/``fundamentals_consumer``): before
  creating a new instrument, check whether ANY row already exists for the
  symbol (ignoring exchange) and reuse/upgrade it instead.

  THIS migration adds a DB-level safety net as defense-in-depth: at most ONE
  placeholder-exchange (``exchange=''``) row may exist per symbol. It cannot
  fully replace the app-level guard (a real-exchange row could still coexist
  with the one allowed placeholder if the app-level guard were ever bypassed
  or raced), but it caps the specific failure mode observed live — repeated
  placeholder-row creation for the same symbol — and gives any future direct
  INSERT a hard, fast-failing signal instead of a silent duplicate.

WHAT THIS MIGRATION DOES:

  Adds a partial unique index on ``upper(symbol)`` filtered to
  ``exchange = ''``, so Postgres itself rejects a second placeholder row for
  the same symbol (case-insensitively).

R11 forward-compat: schema-only migration (no column changes); existing rows
  were already de-duplicated by migration 046, so this index creation cannot
  fail on pre-existing violations in the normal case. Reversible: downgrade
  drops the index.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "047"
down_revision: str = "046"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_instruments_symbol_placeholder_exchange"


def upgrade() -> None:
    # CONCURRENTLY is not usable inside a transactional DDL migration without
    # extra plumbing (op.get_context().autocommit_block()); the ``instruments``
    # table is small (hundreds of rows) so a regular (locking) index build is
    # fine and keeps this migration simple and transactional like its peers.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON instruments (upper(symbol))
        WHERE exchange = ''
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
