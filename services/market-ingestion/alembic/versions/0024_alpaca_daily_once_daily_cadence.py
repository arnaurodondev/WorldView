"""Slow Alpaca 1d OHLCV polling to once-daily (was 6h).

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-17

Rationale
---------
Migration 0023 seeded the ``alpaca / ohlcv / 1d`` polling policies with a 6-hour
cadence (``base_interval_sec = 21600``).  A daily bar only finalizes ONCE per
session (at/after the US close), so a 6h cadence re-fetches the same or partial
daily bar ~4x/day.  Each refetch republishes a ``market.dataset.fetched`` event
carrying the full daily history for that symbol, multiplying the OHLCV consumer's
row volume for zero new data - a direct contributor to the oversized combined
upserts that crash-looped the consumer.

This migration sets the Alpaca 1d cadence to once daily (``86400`` s).  The 1m
cadence is intentionally left untouched (every minute).  Combined with the
repository-side INSERT chunking (market-data), daily polling now produces one
fetch/symbol/day and never overflows the Postgres parameter limit.

Idempotent + reversible
-----------------------
Re-running is a no-op: the UPDATE only touches rows whose interval still differs
from the new value (``WHERE base_interval_sec <> :new``), so a second run matches
nothing.  Downgrade restores the prior 6h cadence for the same policy set.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

# Once-daily cadence for daily bars (a 1d bar closes once per session).
_DAILY_INTERVAL_SEC = 86400
# Prior cadence seeded by 0023 (6h) — restored on downgrade.
_PRIOR_INTERVAL_SEC = 21600


def _set_daily_interval(target_sec: int, prior_sec: int) -> None:
    """Set base/min_interval_sec for alpaca/ohlcv/1d policies to ``target_sec``.

    Only updates rows currently at ``prior_sec`` so the migration is idempotent
    (a re-run matches nothing) and does not clobber any operator-tuned value.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = :target, min_interval_sec = :target, updated_at = NOW() "
            "WHERE provider = 'alpaca' AND dataset_type = 'ohlcv' AND timeframe = '1d' "
            "AND base_interval_sec = :prior"
        ),
        {"target": target_sec, "prior": prior_sec},
    )


def upgrade() -> None:
    _set_daily_interval(_DAILY_INTERVAL_SEC, _PRIOR_INTERVAL_SEC)


def downgrade() -> None:
    _set_daily_interval(_PRIOR_INTERVAL_SEC, _DAILY_INTERVAL_SEC)
