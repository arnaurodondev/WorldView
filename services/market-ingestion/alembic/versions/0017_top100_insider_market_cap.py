"""Add weekly insider_transactions and market_cap policies for top-100 S&P 500.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-06

PLAN-0106 Wave E-1 — Top-100 Insider Transactions + Market Cap.

Rationale
---------
Insider-transaction filings and market-cap snapshots are high-signal inputs
for the intelligence pipeline.  This migration enables weekly polling for
both datasets across the top-100 S&P 500 constituents by approximate market
cap (as of 2026).

Weekly cadence (604800s) is appropriate because:
- SEC Form 4 filings land within 2 business days of the transaction - weekly
  polling captures all filings with a 2-5 day lag, acceptable for analytical
  (not trading) purposes.
- Market-cap snapshots are more relevant at weekly granularity for portfolio
  intelligence than at daily granularity.

All inserts use ``ON CONFLICT (id) DO NOTHING`` so the migration is safe to
re-run.

Forward-compat (R5):
    Only INSERT rows — no schema changes.  Rollback deletes the inserted rows
    by ID.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Deterministic ID helper (copied verbatim from migration 0011)
# ---------------------------------------------------------------------------


def _ulid_from_seed(seed: str) -> str:
    """Deterministic 26-char ULID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


# ---------------------------------------------------------------------------
# Top-100 S&P 500 by approximate market cap (2026 ordering)
# ---------------------------------------------------------------------------
_TOP100_SYMBOLS: list[str] = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "TSLA",
    "AVGO",
    "BRK-B",
    "JPM",
    "LLY",
    "V",
    "UNH",
    "XOM",
    "MA",
    "COST",
    "JNJ",
    "PG",
    "HD",
    "ABBV",
    "WMT",
    "BAC",
    "NFLX",
    "KO",
    "AMD",
    "MRK",
    "CVX",
    "ORCL",
    "CRM",
    "ADBE",
    "PEP",
    "TMO",
    "ACN",
    "LIN",
    "MCD",
    "CSCO",
    "IBM",
    "ABT",
    "GE",
    "CAT",
    "QCOM",
    "INTU",
    "DHR",
    "AMAT",
    "AXP",
    "TXN",
    "GS",
    "ISRG",
    "VZ",
    "SPGI",
    "BKNG",
    "RTX",
    "BA",
    "MS",
    "NOW",
    "AMGN",
    "BLK",
    "SYK",
    "PGR",
    "PANW",
    "GILD",
    "ADP",
    "HON",
    "CI",
    "LOW",
    "ELV",
    "T",
    "MDT",
    "PLD",
    "BSX",
    "REGN",
    "VRTX",
    "MU",
    "LRCX",
    "CME",
    "CB",
    "KLAC",
    "DUK",
    "SO",
    "COP",
    "SCHW",
    "MMC",
    "ITW",
    "SBUX",
    "DE",
    "ICE",
    "SHW",
    "MO",
    "WM",
    "MCO",
    "TGT",
    "USB",
    "NOC",
    "APD",
    "EOG",
    "PH",
    "FDX",
    "AON",
    "HLT",
]


# ---------------------------------------------------------------------------
# ID helpers for downgrade
# ---------------------------------------------------------------------------


def _all_insider_ids() -> list[str]:
    return [_ulid_from_seed(f"eodhd:insider_transactions:{sym}:US:::") for sym in _TOP100_SYMBOLS]


def _all_market_cap_ids() -> list[str]:
    return [_ulid_from_seed(f"eodhd:market_cap:{sym}:US:::") for sym in _TOP100_SYMBOLS]


# ---------------------------------------------------------------------------
# Upgrade / Downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    conn = op.get_bind()

    insert_sql = sa.text(
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
    )

    for sym in _TOP100_SYMBOLS:
        # insider_transactions — weekly, priority 1
        conn.execute(
            insert_sql,
            {
                "id": _ulid_from_seed(f"eodhd:insider_transactions:{sym}:US:::"),
                "provider": "eodhd",
                "dataset_type": "insider_transactions",
                "dataset_variant": None,
                "symbol": sym,
                "exchange": "US",
                "timeframe": None,
                "base_interval_sec": 604800,
                "min_interval_sec": 3600,
                "jitter_sec": 300,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 1,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": False,
                "tier": 2,
                "post_market_only": False,
                "created_at": now,
                "updated_at": now,
            },
        )

        # market_cap — weekly, priority 1
        conn.execute(
            insert_sql,
            {
                "id": _ulid_from_seed(f"eodhd:market_cap:{sym}:US:::"),
                "provider": "eodhd",
                "dataset_type": "market_cap",
                "dataset_variant": None,
                "symbol": sym,
                "exchange": "US",
                "timeframe": None,
                "base_interval_sec": 604800,
                "min_interval_sec": 3600,
                "jitter_sec": 300,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 1,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": False,
                "tier": 2,
                "post_market_only": False,
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    all_ids = _all_insider_ids() + _all_market_cap_ids()
    conn.execute(
        sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=all_ids, type_=sa.ARRAY(sa.String))
        )
    )
