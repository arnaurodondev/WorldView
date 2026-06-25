"""Disable weekly (1w) and monthly (1mo) OHLCV polling — bars are now DERIVED.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-15

Rationale
---------
Weekly (``1w``) and monthly (``1mo``) OHLCV bars are now served by the
market-data (S3) ``GET /api/v1/ohlcv/bars`` endpoint as DERIVED temporalities —
aggregated on the fly at query time from the stored daily (``1d``) bars
(PLAN-0036 design intent: "eliminate provider polling for the 1W and 1M
timeframes by deriving locally").

The S2 polling side, however, still seeds ``1w``/``1mo`` OHLCV polling policies
(seed migrations 0002/0004/0005/0014).  In practice these polls return EMPTY
payloads — a watermark-bounded incremental window is typically a single recent
day, while a weekly bar only closes on Fridays and a monthly bar on month-end,
so Yahoo/EODHD return zero rows for almost every poll.  The investigation
(``docs/audits/2026-06-15-weekly-monthly-bar-aggregation-investigation.md``)
found ~6,900 "succeeded" tasks carrying the empty-input SHA
``e3b0c442…`` — pure noise: Kafka traffic, watermark churn, task-table growth,
and zero usable data.  The rare non-empty ``1mo`` payload would additionally be
mislabeled as daily by an S3 consumer enum-coercion bug (fixed separately).

Since weekly/monthly are now DERIVED locally, the polling path is fully
redundant.  This migration disables every ``dataset_type='ohlcv'`` polling
policy whose ``timeframe`` is ``1w`` or ``1mo`` (any provider), across all seeded
symbols.  The scheduler tick loop and the startup-backfill pass both select
only ``enabled = TRUE`` policies (``policy_repository.list_enabled()``), so
flipping the flag stops both 1w/1mo polling AND any 1w/1mo backfill — no code
change is required, the scheduler never hardcodes these timeframes.

Daily (``1d``) and intraday (Alpaca ``1m``) ingestion are left UNTOUCHED — they
remain the source of truth that weekly/monthly are derived from.

Idempotent + conservative (R5)
------------------------------
Data-only UPDATE (no schema change).  Re-running is a no-op (already disabled
rows match the WHERE again but the SET is identical).  Downgrade re-enables the
same rows, restoring the prior (noisy) behaviour.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# Timeframes that are now derived locally and must no longer be polled.
_DERIVED_TIMEFRAMES = ("1w", "1mo")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' "
            "AND timeframe IN ('1w', '1mo') "
            "AND enabled = true"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' "
            "AND timeframe IN ('1w', '1mo') "
            "AND enabled = false"
        )
    )
