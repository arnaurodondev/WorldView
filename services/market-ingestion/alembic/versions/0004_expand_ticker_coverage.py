"""Expand ticker coverage from 6 to 64 symbols.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-24

For live systems that already ran 0002 with the original 6-ticker seed list
(AAPL, TSLA, VTI, AMZN, BTC-USD, EURUSD), this migration adds polling policies
for the remaining 58 symbols: top-30 US equities, sector/broad-market/fixed-income/
commodity ETFs, major indices, and the top-10 cryptocurrencies.

The original 6 symbols are intentionally skipped — their policies were created by
0002 and this migration must not duplicate them.  INSERT … WHERE NOT EXISTS guards
are applied at the SQL level so the migration is safe to run even if 0002 was
already updated to include the full 64-symbol list (i.e., on a fresh database the
inserts are no-ops for rows that already exist).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers (mirrors 0002 so IDs are identical — deterministic hash)
# ---------------------------------------------------------------------------


def _ulid_from_seed(seed: str) -> str:
    """Generate a deterministic 26-char ULID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


_POLICIES_TABLE = sa.table(
    "polling_policies",
    sa.column("id", sa.String),
    sa.column("provider", sa.String),
    sa.column("dataset_type", sa.String),
    sa.column("dataset_variant", sa.String),
    sa.column("symbol", sa.String),
    sa.column("exchange", sa.String),
    sa.column("timeframe", sa.String),
    sa.column("base_interval_sec", sa.Integer),
    sa.column("min_interval_sec", sa.Integer),
    sa.column("jitter_sec", sa.Integer),
    sa.column("adaptive_enabled", sa.Boolean),
    sa.column("adaptive_k", sa.Float),
    sa.column("adaptive_half_life_sec", sa.Integer),
    sa.column("priority", sa.Integer),
    sa.column("enabled", sa.Boolean),
    sa.column("backfill_enabled", sa.Boolean),
    sa.column("backfill_start_date", sa.Date),
    sa.column("backfill_chunk_days", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    # market_hours_only was added by 0003 — must be present so bulk_insert succeeds
    sa.column("market_hours_only", sa.Boolean),
)

# ---------------------------------------------------------------------------
# The original 6 symbols seeded by 0002 — excluded from this migration so
# we never create duplicate policies on systems that already ran 0002.
# ---------------------------------------------------------------------------
_ORIGINAL_SYMBOLS: frozenset[tuple[str, str]] = frozenset(
    [
        ("AAPL", "US"),
        ("TSLA", "US"),
        ("VTI", "US"),
        ("AMZN", "US"),
        ("BTC-USD", "CC"),
        ("EURUSD", "FOREX"),
    ]
)

# ---------------------------------------------------------------------------
# New symbols to add — the full expanded list minus the original 6.
# Order within each category is intentional (largest-cap / most-liquid first).
# ---------------------------------------------------------------------------
_NEW_SYMBOLS: list[tuple[str, str]] = [
    # ── Top 30 US Equities (S&P 500 leaders, sector-diverse) ──────────────────
    ("MSFT", "US"),
    ("GOOGL", "US"),
    ("NVDA", "US"),
    ("META", "US"),
    ("BRK-B", "US"),
    ("JNJ", "US"),
    ("V", "US"),
    ("WMT", "US"),
    ("JPM", "US"),
    ("PG", "US"),
    ("XOM", "US"),
    ("MA", "US"),
    ("UNH", "US"),
    ("HD", "US"),
    ("COST", "US"),
    ("MRK", "US"),
    ("BA", "US"),
    ("PFE", "US"),
    ("LLY", "US"),
    ("AXP", "US"),
    ("MS", "US"),
    ("DIS", "US"),
    ("IBM", "US"),
    ("EXC", "US"),
    ("CAT", "US"),
    ("KO", "US"),
    ("CVX", "US"),
    # ── Mandatory Sector ETFs ─────────────────────────────────────────────────
    ("XLK", "US"),  # Technology
    ("XLV", "US"),  # Health Care
    ("XLE", "US"),  # Energy
    ("XLY", "US"),  # Consumer Discretionary
    ("VTV", "US"),  # Vanguard Value
    ("QQQ", "US"),  # Nasdaq 100
    ("IBIT", "US"),  # iShares Bitcoin Mini Trust
    ("MSTR", "US"),  # MicroStrategy (crypto-correlated equity)
    ("PPA", "US"),  # Invesco Aerospace & Defense
    # ── Broad Market ETFs ─────────────────────────────────────────────────────
    ("SPY", "US"),
    ("IVV", "US"),
    ("VOO", "US"),
    # VTI is already in _ORIGINAL_SYMBOLS — intentionally omitted here
    # ── Fixed Income ETFs ─────────────────────────────────────────────────────
    ("IEF", "US"),  # 7-10Y Treasuries
    ("TLT", "US"),  # 20+Y Treasuries
    ("AGG", "US"),  # Aggregate Bonds
    ("SHY", "US"),  # 1-3Y Treasuries
    # ── Commodity ETFs ────────────────────────────────────────────────────────
    ("GLD", "US"),  # Gold
    ("SLV", "US"),  # Silver
    ("USO", "US"),  # Oil
    # ── Major Indices ─────────────────────────────────────────────────────────
    ("GSPC", "INDX"),  # S&P 500
    ("CCMP", "INDX"),  # NASDAQ Composite
    ("INDU", "INDX"),  # Dow Jones Industrial Average
    ("RUT", "INDX"),  # Russell 2000
    ("VIX", "INDX"),  # CBOE Volatility Index
    # ── Top 10 Cryptocurrencies by market cap (BTC-USD already in original) ───
    ("ETH-USD", "CC"),
    ("BNB-USD", "CC"),
    ("SOL-USD", "CC"),
    ("XRP-USD", "CC"),
    ("ADA-USD", "CC"),
    ("DOGE-USD", "CC"),
    ("AVAX-USD", "CC"),
    ("MATIC-USD", "CC"),
    ("LTC-USD", "CC"),
]

# Sanity-check: none of the new symbols should overlap with the originals.
assert not (frozenset(_NEW_SYMBOLS) & _ORIGINAL_SYMBOLS), "Overlap detected between _NEW_SYMBOLS and _ORIGINAL_SYMBOLS"


def _new_policy_ids() -> list[str]:
    """Return all deterministic IDs created by this migration (for downgrade)."""
    ids: list[str] = []
    for symbol, exchange in _NEW_SYMBOLS:
        ids.append(_ulid_from_seed(f"eodhd:quotes:{symbol}:{exchange}::"))
        for tf in ("1d", "1w", "1mo"):
            ids.append(_ulid_from_seed(f"eodhd:ohlcv:{symbol}:{exchange}:{tf}:"))
        ids.append(_ulid_from_seed(f"eodhd:fundamentals:{symbol}:{exchange}::General"))
    return ids


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    policies: list[dict] = []

    for symbol, exchange in _NEW_SYMBOLS:
        # quotes policy — adaptive, high-priority, polled every 5 minutes.
        # market_hours_only=True because 0003 already set this for all quote policies
        # on the original symbols; we apply the same flag here for consistency.
        policies.append(
            {
                "id": _ulid_from_seed(f"eodhd:quotes:{symbol}:{exchange}::"),
                "provider": "eodhd",
                "dataset_type": "quotes",
                "dataset_variant": None,
                "symbol": symbol,
                "exchange": exchange,
                "timeframe": None,
                "base_interval_sec": 300,
                "min_interval_sec": 60,
                "jitter_sec": 10,
                "adaptive_enabled": True,
                "adaptive_k": 1.5,
                "adaptive_half_life_sec": 1800,
                "priority": 10,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": True,
                "created_at": now,
                "updated_at": now,
            }
        )

        # ohlcv policies — one per timeframe (1d / 1w / 1mo)
        for tf, base_int, prio in [("1d", 21600, 5), ("1w", 43200, 4), ("1mo", 86400, 3)]:
            policies.append(
                {
                    "id": _ulid_from_seed(f"eodhd:ohlcv:{symbol}:{exchange}:{tf}:"),
                    "provider": "eodhd",
                    "dataset_type": "ohlcv",
                    "dataset_variant": None,
                    "symbol": symbol,
                    "exchange": exchange,
                    "timeframe": tf,
                    "base_interval_sec": base_int,
                    "min_interval_sec": 3600,
                    "jitter_sec": 60,
                    "adaptive_enabled": False,
                    "adaptive_k": 1.0,
                    "adaptive_half_life_sec": 3600,
                    "priority": prio,
                    "enabled": True,
                    "backfill_enabled": False,
                    "backfill_start_date": None,
                    "backfill_chunk_days": None,
                    "market_hours_only": False,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        # fundamentals policy — daily, low-priority
        policies.append(
            {
                "id": _ulid_from_seed(f"eodhd:fundamentals:{symbol}:{exchange}::General"),
                "provider": "eodhd",
                "dataset_type": "fundamentals",
                "dataset_variant": "General",
                "symbol": symbol,
                "exchange": exchange,
                "timeframe": None,
                "base_interval_sec": 86400,
                "min_interval_sec": 3600,
                "jitter_sec": 300,
                "adaptive_enabled": False,
                "adaptive_k": 1.0,
                "adaptive_half_life_sec": 3600,
                "priority": 2,
                "enabled": True,
                "backfill_enabled": False,
                "backfill_start_date": None,
                "backfill_chunk_days": None,
                "market_hours_only": False,
                "created_at": now,
                "updated_at": now,
            }
        )

    # Use INSERT … ON CONFLICT DO NOTHING so this migration is idempotent on
    # databases where 0002 was already updated to include the full 64-symbol list.
    conn = op.get_bind()
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
                    market_hours_only, created_at, updated_at
                ) VALUES (
                    :id, :provider, :dataset_type, :dataset_variant,
                    :symbol, :exchange, :timeframe,
                    :base_interval_sec, :min_interval_sec, :jitter_sec,
                    :adaptive_enabled, :adaptive_k, :adaptive_half_life_sec,
                    :priority, :enabled, :backfill_enabled,
                    :backfill_start_date, :backfill_chunk_days,
                    :market_hours_only, :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            policy,
        )


def downgrade() -> None:
    ids = _new_policy_ids()
    op.execute(
        sa.text("DELETE FROM polling_policies WHERE id = ANY(:ids)").bindparams(
            sa.bindparam("ids", value=ids, type_=sa.ARRAY(sa.String))
        )
    )
