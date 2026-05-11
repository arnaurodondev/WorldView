"""Add Alpaca 1-minute OHLCV polling policies; disable redundant EODHD 5m/1h.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-28

Rationale
---------
The intraday resampling pipeline (market-data service) now derives 5m / 15m /
30m / 1h / 4h / 1d bars from the finest source timeframe (default: 1m, driven
by MARKET_DATA_INTRADAY_SOURCE_TF).  Fetching 5m and 1h directly from EODHD
is therefore redundant and burns API credits.  This migration:

1. Inserts Alpaca 1m OHLCV polling policies for every compatible symbol
   (US-exchange equities + ETFs, and CC-exchange crypto).  Index (INDX) and
   Forex symbols are excluded — Alpaca does not provide them.

2. Disables the EODHD 5m policies for AAPL and TSLA.

3. Disables the EODHD 1h policies for AAPL, TSLA, AMZN, BTC-USD, and EURUSD.
   (EURUSD 1h is disabled even though Alpaca does not cover Forex — the 1h bar
   will be derived once a Forex adapter is wired up at any timeframe.)

4. Adds an Alpaca provider_budget row (Alpaca Free allows unlimited unlimited
   historical bar requests; the budget is set permissively to avoid blocking.)

Alpaca policy settings
-----------------------
- base_interval_sec=60   — poll every 1 minute
- market_hours_only=True for US equities/ETFs (Alpaca SIP feed covers RTH)
- market_hours_only=False for crypto (24/7)
- tier=1                 — highest-priority, finest granularity
- post_market_only=False
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


# ---------------------------------------------------------------------------
# Symbols for which Alpaca provides 1m OHLCV bars.
# INDX and FOREX are excluded — Alpaca does not cover them.
# ---------------------------------------------------------------------------

# US-exchange equities and ETFs — market_hours_only=True
_US_SYMBOLS: list[str] = [
    # Top 30 US Equities
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "TSLA",
    "META",
    "BRK-B",
    "JNJ",
    "V",
    "WMT",
    "JPM",
    "PG",
    "XOM",
    "MA",
    "UNH",
    "HD",
    "COST",
    "MRK",
    "BA",
    "PFE",
    "LLY",
    "AXP",
    "MS",
    "DIS",
    "IBM",
    "EXC",
    "CAT",
    "KO",
    "CVX",
    # Sector ETFs
    "XLK",
    "XLV",
    "XLE",
    "XLY",
    "VTV",
    "QQQ",
    "IBIT",
    "MSTR",
    "PPA",
    # Broad Market ETFs
    "SPY",
    "IVV",
    "VOO",
    "VTI",
    # Fixed Income ETFs
    "IEF",
    "TLT",
    "AGG",
    "SHY",
    # Commodity ETFs
    "GLD",
    "SLV",
    "USO",
]

# Crypto (CC exchange) — market_hours_only=False (trades 24/7)
_CC_SYMBOLS: list[str] = [
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
]

# EODHD intraday policies to disable (replaced by derivation from 1m Alpaca bars)
_EODHD_5M_SYMBOLS: list[tuple[str, str]] = [("AAPL", "US"), ("TSLA", "US")]
_EODHD_1H_SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "US"),
    ("TSLA", "US"),
    ("AMZN", "US"),
    ("BTC-USD", "CC"),
    ("EURUSD", "FOREX"),
]

_ALPACA_BUDGET_ID = _ulid_from_seed("alpaca:provider_budget:alpaca")


def _all_alpaca_policy_ids() -> list[str]:
    ids: list[str] = []
    for sym in _US_SYMBOLS:
        ids.append(_ulid_from_seed(f"alpaca:ohlcv:{sym}:US:1m:"))
    for sym in _CC_SYMBOLS:
        ids.append(_ulid_from_seed(f"alpaca:ohlcv:{sym}:CC:1m:"))
    return ids


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Insert Alpaca 1m OHLCV policies — ON CONFLICT DO NOTHING so the
    #    migration is safe to re-run on databases that already have them.
    # ------------------------------------------------------------------
    policies: list[dict] = []

    for sym in _US_SYMBOLS:
        policies.append(
            {
                "id": _ulid_from_seed(f"alpaca:ohlcv:{sym}:US:1m:"),
                "provider": "alpaca",
                "dataset_type": "ohlcv",
                "dataset_variant": None,
                "symbol": sym,
                "exchange": "US",
                "timeframe": "1m",
                "base_interval_sec": 60,
                "min_interval_sec": 60,
                "jitter_sec": 5,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 20,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": True,
                "tier": 1,
                "post_market_only": False,
                "created_at": now,
                "updated_at": now,
            }
        )

    for sym in _CC_SYMBOLS:
        policies.append(
            {
                "id": _ulid_from_seed(f"alpaca:ohlcv:{sym}:CC:1m:"),
                "provider": "alpaca",
                "dataset_type": "ohlcv",
                "dataset_variant": None,
                "symbol": sym,
                "exchange": "CC",
                "timeframe": "1m",
                "base_interval_sec": 60,
                "min_interval_sec": 60,
                "jitter_sec": 5,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 20,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": False,
                "tier": 1,
                "post_market_only": False,
                "created_at": now,
                "updated_at": now,
            }
        )

    for policy in policies:
        conn.execute(
            sa.text(
                """
                INSERT INTO polling_policies (
                    id, provider, dataset_type, dataset_variant,
                    symbol, exchange, timeframe,
                    base_interval_sec, min_interval_sec, jitter_sec,
                    adaptive_enabled, adaptive_k, adaptive_half_life_sec,
                    priority, enabled, backfill_enabled,
                    backfill_start_date, backfill_chunk_days,
                    market_hours_only, tier, post_market_only,
                    created_at, updated_at
                ) VALUES (
                    :id, :provider, :dataset_type, :dataset_variant,
                    :symbol, :exchange, :timeframe,
                    :base_interval_sec, :min_interval_sec, :jitter_sec,
                    :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                    :priority, :enabled, :backfill_enabled,
                    :backfill_start_date, :backfill_chunk_days,
                    :market_hours_only, :tier, :post_market_only,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            policy,
        )

    # ------------------------------------------------------------------
    # 2. Disable EODHD 5m policies — derivation covers these from 1m.
    # ------------------------------------------------------------------
    eodhd_5m_symbols = [s for s, _ in _EODHD_5M_SYMBOLS]
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '5m' AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=eodhd_5m_symbols, type_=sa.ARRAY(sa.String)))
    )

    # ------------------------------------------------------------------
    # 3. Disable EODHD 1h policies — derivation covers these from 1m.
    # ------------------------------------------------------------------
    eodhd_1h_symbols = [s for s, _ in _EODHD_1H_SYMBOLS]
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = false, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1h' AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=eodhd_1h_symbols, type_=sa.ARRAY(sa.String)))
    )

    # ------------------------------------------------------------------
    # 4. Insert Alpaca provider budget (permissive — Alpaca Free has no
    #    hard rate limit on historical bar requests; budget prevents runaway).
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            """
            INSERT INTO provider_budgets (
                id, provider, max_tokens, current_tokens,
                refill_rate_per_second, last_refill_at, created_at, updated_at
            ) VALUES (
                :id, 'alpaca', 10000, 10000.0, 10.0, :now, :now, :now
            )
            ON CONFLICT (provider) DO NOTHING
            """
        ),
        {"id": _ALPACA_BUDGET_ID, "now": now},
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove all Alpaca 1m policies inserted by this migration
    alpaca_ids = _all_alpaca_policy_ids()
    conn.execute(
        sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=alpaca_ids, type_=sa.ARRAY(sa.String))
        )
    )

    # Remove Alpaca provider budget
    conn.execute(sa.text("DELETE FROM provider_budgets WHERE id = :id").bindparams(id=_ALPACA_BUDGET_ID))

    # Re-enable EODHD 5m and 1h policies
    eodhd_5m_symbols = [s for s, _ in _EODHD_5M_SYMBOLS]
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '5m' AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=eodhd_5m_symbols, type_=sa.ARRAY(sa.String)))
    )
    eodhd_1h_symbols = [s for s, _ in _EODHD_1H_SYMBOLS]
    conn.execute(
        sa.text(
            "UPDATE polling_policies "
            "SET enabled = true, updated_at = NOW() "
            "WHERE provider = 'eodhd' AND dataset_type = 'ohlcv' "
            "AND timeframe = '1h' AND symbol = ANY(:symbols)"
        ).bindparams(sa.bindparam("symbols", value=eodhd_1h_symbols, type_=sa.ARRAY(sa.String)))
    )
