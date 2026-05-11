"""API call optimisation - reduce EODHD credit consumption by ~73%.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-24

Changes applied:
  1. Fundamentals interval: 86400 s (1 day) -> 604800 s (7 days).
     Fundamental data (P&L, balance sheet) changes quarterly at most; daily
     fetching burns 640 EODHD credits/day (64 x 10) for no incremental value.
  2. Fundamentals disabled for non-equity instruments.
     Crypto (CC exchange), major indices (INDX exchange), and most fixed-income
     commodity ETFs have no financial statements. These are pure price-series
     instruments for which the fundamentals endpoint returns sparse or empty data.
     Disabling saves 10 credits x N disabled symbols per weekly refresh.
  3. Intraday 5m OHLCV marked market_hours_only=True.
     AAPL and TSLA 5-minute bars cost 5 credits each. Polling 24/7 wastes
     ~2880 credits/day; market-hours gating reduces this to ~600 credits/day.
  4. Intraday 1h OHLCV marked market_hours_only=True.
     Same rationale - 5 credits x 5 symbols x 24 h = 600 credits/day -> ~125/day.
  5. Budget max_tokens raised to 2000 and refill_rate lowered to 1.16/s.
     Old refill rate (10/s) equated to 864000 tokens/day - effectively unlimited.
     New rate = 100000 credits/day / 86400 s = 1.157/s, matching the EODHD
     daily limit so the budget actually enforces the cap.

Note: 1w and 1mo OHLCV policies are left enabled but their interval is extended
to weekly (604800 s) and monthly (2592000 s) respectively. Derived aggregation
from 1d data is a future optimisation tracked separately.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Instruments without company financial statements — fundamentals disabled.
# ---------------------------------------------------------------------------

# Cryptocurrency symbols (CC exchange in EODHD)
_CRYPTO_SYMBOLS = (
    "BTC-USD",
    "ETH-USD",
    "BNB-USD",
    "SOL-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
    "AVAX-USD",
    "MATIC-USD",
    "LTC-USD",
)

# Major market indices (INDX exchange in EODHD)
_INDEX_SYMBOLS = ("GSPC", "CCMP", "INDU", "RUT", "VIX")

# Commodity ETFs — track commodity futures prices, no financial statements
_COMMODITY_ETF_SYMBOLS = ("GLD", "SLV", "USO")

# Intraday symbols needing market_hours_only gate
_INTRADAY_5M_SYMBOLS = ("AAPL", "TSLA")
_INTRADAY_1H_SYMBOLS = ("AAPL", "TSLA", "AMZN", "BTC-USD", "EURUSD")


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Extend fundamentals refresh interval from 1 day to 7 days.
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 604800, updated_at = NOW() "
            "WHERE dataset_type = 'fundamentals' AND provider = 'eodhd'"
        )
    )

    # ------------------------------------------------------------------
    # 2. Disable fundamentals for non-equity instruments.
    # ------------------------------------------------------------------
    all_non_equity = list(_CRYPTO_SYMBOLS) + list(_INDEX_SYMBOLS) + list(_COMMODITY_ETF_SYMBOLS)
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE dataset_type = 'fundamentals' "
            "AND provider = 'eodhd' "
            "AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=all_non_equity, type_=sa.ARRAY(sa.String)))
    )

    # ------------------------------------------------------------------
    # 3. Extend 1w OHLCV to weekly interval (43 200 s → 604 800 s).
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 604800, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '1w' AND provider = 'eodhd'"
        )
    )

    # ------------------------------------------------------------------
    # 4. Extend 1mo OHLCV to monthly interval (86 400 s → 2 592 000 s).
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 2592000, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '1mo' AND provider = 'eodhd'"
        )
    )

    # ------------------------------------------------------------------
    # 5. Gate 5m intraday to market hours only.
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET market_hours_only = true, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '5m' "
            "AND provider = 'eodhd' "
            "AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=list(_INTRADAY_5M_SYMBOLS), type_=sa.ARRAY(sa.String)))
    )

    # ------------------------------------------------------------------
    # 6. Gate 1h intraday to market hours only.
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET market_hours_only = true, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '1h' "
            "AND provider = 'eodhd' "
            "AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=list(_INTRADAY_1H_SYMBOLS), type_=sa.ARRAY(sa.String)))
    )

    # ------------------------------------------------------------------
    # 7. Recalibrate provider budget to match EODHD daily limit.
    #    Old: max=1 000, refill=10/s → effectively unlimited (864 000/day)
    #    New: max=2 000, refill≈1.157/s → 100 000 credits/day (EODHD limit)
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            "UPDATE provider_budgets "
            "SET max_tokens = 2000, refill_rate_per_second = 1.157, updated_at = NOW() "
            "WHERE provider = 'eodhd'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Restore fundamentals to daily and re-enable for all symbols
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 86400, enabled = true, updated_at = NOW() "
            "WHERE dataset_type = 'fundamentals' AND provider = 'eodhd'"
        )
    )

    # Restore 1w/1mo OHLCV intervals
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 43200, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '1w' AND provider = 'eodhd'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET base_interval_sec = 86400, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe = '1mo' AND provider = 'eodhd'"
        )
    )

    # Remove market_hours_only gate from intraday
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET market_hours_only = false, updated_at = NOW() "
            "WHERE dataset_type = 'ohlcv' AND timeframe IN ('5m', '1h') AND provider = 'eodhd'"
        )
    )

    # Restore original budget
    conn.execute(
        sa.text(
            "UPDATE provider_budgets "
            "SET max_tokens = 1000, refill_rate_per_second = 10.0, updated_at = NOW() "
            "WHERE provider = 'eodhd'"
        )
    )
