"""Merge phantom ``.USD`` crypto instruments into their ``-USD`` canonicals.

Revision ID: 036
Revises: 035
Create Date: 2026-06-11

Background
----------
``_normalize_ticker`` blanket-rewrote ``-`` to ``.`` (added for BRK-B ->
BRK.B), which also rewrote canonical crypto pairs: ``BTC-USD`` -> ``BTC.USD``.
The OHLCV consumer then missed the existing ``-USD`` instrument on lookup and
auto-created a ``.USD`` duplicate — 17 phantom instruments, each holding the
intraday/derived bars that should live on the ``-USD`` row. The code fix (a
crypto exemption in ``_normalize_ticker``) ships in the same commit; this
migration repairs the data:

1. Re-key every ``ohlcv_bars`` row from each ``.USD`` instrument to its
   ``-USD`` sibling (matched via ``replace(symbol, '.', '-')``). Implemented
   as INSERT ... SELECT ... ON CONFLICT DO NOTHING because ohlcv_bars is a
   TimescaleDB hypertable with PK (instrument_id, timeframe, bar_date) and an
   UPDATE colliding with an existing canonical bar would abort; the canonical
   bar wins on conflict.
2. DELETE the ``.USD`` instruments. Every referencing table (ohlcv_bars,
   quotes, the fundamentals/snapshot tables, ...) declares
   ON DELETE CASCADE, so the leftover duplicate rows are swept automatically.

Only ``.USD`` instruments WITH a ``-USD`` sibling are touched — a hypothetical
legitimate ``.USD`` symbol without a hyphenated twin is left alone.

Cross-DB note (R9/R24)
----------------------
The wrong ``.USD`` Alpaca polling policies live in ingestion_db, which this
service's migrations must not touch. Run manually instead (data-only)::

    docker exec worldview-postgres-1 psql -U postgres -d ingestion_db -c \
      "DELETE FROM polling_policies WHERE provider='alpaca' AND symbol LIKE '%.USD';"

Downgrade
---------
Irreversible data merge — downgrade is a no-op (the phantom instruments were
artifacts of a bug; recreating them would re-introduce the fragmentation).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1: copy bars from each .USD duplicate onto its -USD canonical ──
    # Set-based over all duplicates at once; ON CONFLICT keeps the canonical
    # instrument's existing bar when both rows cover the same (tf, bar_date).
    conn.execute(
        sa.text(
            """
            INSERT INTO ohlcv_bars (
                instrument_id, timeframe, bar_date, open, high, low, close,
                volume, adjusted_close, source, provider_priority,
                is_derived, is_partial
            )
            SELECT canon.id, b.timeframe, b.bar_date, b.open, b.high, b.low,
                   b.close, b.volume, b.adjusted_close, b.source,
                   b.provider_priority, b.is_derived, b.is_partial
            FROM ohlcv_bars b
            JOIN instruments dup ON dup.id = b.instrument_id
            JOIN instruments canon ON canon.symbol = replace(dup.symbol, '.', '-')
            WHERE dup.symbol LIKE '%.USD'
            ON CONFLICT (instrument_id, timeframe, bar_date) DO NOTHING
            """
        )
    )

    # ── Step 2: drop the phantom .USD instruments (cascades sweep the rest) ─
    conn.execute(
        sa.text(
            """
            DELETE FROM instruments dup
            USING instruments canon
            WHERE dup.symbol LIKE '%.USD'
              AND canon.symbol = replace(dup.symbol, '.', '-')
            """
        )
    )


def downgrade() -> None:
    # Irreversible data merge — see module docstring.
    pass
