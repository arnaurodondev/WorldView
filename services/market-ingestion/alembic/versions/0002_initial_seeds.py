"""Initial seed data for the market-ingestion service.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-12

Seeds polling policies and provider budgets for demo-safe EODHD defaults.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _ulid_from_seed(seed: str) -> str:
    """Generate a deterministic 26-char ULID-like ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"01HX{h[:22].upper()}"


# Budget row uses a fixed deterministic seed (not positional) so it is stable
# regardless of how many policy symbols are defined above it.
_BUDGET_ID = _ulid_from_seed("eodhd:provider_budget:eodhd")

_SYMBOLS: list[tuple[str, str]] = [
    # ── Top 30 US Equities (S&P 500 leaders, sector-diverse) ──────────────────
    ("AAPL", "US"),
    ("MSFT", "US"),
    ("GOOGL", "US"),
    ("AMZN", "US"),
    ("NVDA", "US"),
    ("TSLA", "US"),
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
    ("VTI", "US"),
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
    # ── Top 10 Cryptocurrencies by market cap ─────────────────────────────────
    ("BTC-USD", "CC"),
    ("ETH-USD", "CC"),
    ("BNB-USD", "CC"),
    ("SOL-USD", "CC"),
    ("XRP-USD", "CC"),
    ("ADA-USD", "CC"),
    ("DOGE-USD", "CC"),
    ("AVAX-USD", "CC"),
    ("MATIC-USD", "CC"),
    ("LTC-USD", "CC"),
    # ── Forex ─────────────────────────────────────────────────────────────────
    ("EURUSD", "FOREX"),
]

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
)

_BUDGETS_TABLE = sa.table(
    "provider_budgets",
    sa.column("id", sa.String),
    sa.column("provider", sa.String),
    sa.column("max_tokens", sa.Integer),
    sa.column("current_tokens", sa.Float),
    sa.column("refill_rate_per_second", sa.Float),
    sa.column("last_refill_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _insert_policy(
    provider: str,
    dataset_type: str,
    symbol: str,
    exchange: str,
    timeframe: str,
    variant: str,
    interval_s: int,
    priority: int = 0,
) -> None:
    seed = f"{provider}:{dataset_type}:{symbol}:{exchange}:{timeframe}:{variant}"
    op.execute(
        _POLICIES_TABLE.insert().values(
            id=_ulid_from_seed(seed),
            provider=provider,
            dataset_type=dataset_type,
            dataset_variant=variant or None,
            symbol=symbol or None,
            exchange=exchange or None,
            timeframe=timeframe or None,
            base_interval_sec=interval_s,
            min_interval_sec=max(60, interval_s // 10),
            jitter_sec=10,
            adaptive_enabled=False,
            adaptive_k=1.0,
            adaptive_half_life_sec=3600,
            priority=priority,
            enabled=True,
            backfill_enabled=False,
            backfill_start_date=None,
            backfill_chunk_days=None,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
    )


def _core_policy_ids() -> list[str]:
    """Return all deterministic IDs for the core per-symbol policies (quotes + ohlcv + fundamentals)."""
    ids: list[str] = []
    for symbol, exchange in _SYMBOLS:
        ids.append(_ulid_from_seed(f"eodhd:quotes:{symbol}:{exchange}::"))
        for tf in ("1d", "1w", "1mo"):
            ids.append(_ulid_from_seed(f"eodhd:ohlcv:{symbol}:{exchange}:{tf}:"))
        ids.append(_ulid_from_seed(f"eodhd:fundamentals:{symbol}:{exchange}::General"))
    return ids


def _extended_seed_ids() -> list[str]:
    ids: list[str] = []

    for sym, exch in [("AAPL", "US"), ("TSLA", "US"), ("AMZN", "US"), ("BTC-USD", "CC"), ("EURUSD", "FOREX")]:
        ids.append(_ulid_from_seed(f"eodhd:ohlcv:{sym}:{exch}:1h:"))

    for sym in ["AAPL", "TSLA"]:
        ids.append(_ulid_from_seed(f"eodhd:ohlcv:{sym}:US:5m:"))

    ids.append(_ulid_from_seed("eodhd:earnings_calendar:CALENDAR:EARNINGS::"))

    for country in ["USA", "EUR", "GBR"]:
        ids.append(_ulid_from_seed(f"eodhd:economic_events:EVENTS.{country}::::"))

    for indicator in ["gdp_current_usd", "inflation_consumer_prices_annual", "unemployment_total_pct"]:
        ids.append(_ulid_from_seed(f"eodhd:macro_indicator:USA.{indicator}::::"))
    for indicator in ["gdp_current_usd", "inflation_consumer_prices_annual"]:
        ids.append(_ulid_from_seed(f"eodhd:macro_indicator:EUR.{indicator}::::"))

    for sym, exch in [("AAPL", "US"), ("TSLA", "US"), ("AMZN", "US"), ("BTC-USD", "CC")]:
        ids.append(_ulid_from_seed(f"eodhd:news_sentiment:{sym}:{exch}:::"))

    for sym in ["AAPL", "TSLA", "AMZN"]:
        ids.append(_ulid_from_seed(f"eodhd:insider_transactions:{sym}:US:::"))

    for series in ["UST.yield", "UST.bill", "UST.longterm"]:
        ids.append(_ulid_from_seed(f"eodhd:yield_curve:{series}::::"))

    for sym in ["AAPL", "TSLA", "AMZN", "VTI", "BRK-B"]:
        ids.append(_ulid_from_seed(f"eodhd:market_cap:{sym}:US:::"))

    return ids


def upgrade() -> None:
    now = datetime.now(tz=UTC)
    policies: list[dict] = []

    for symbol, exchange in _SYMBOLS:
        # quotes policy — adaptive, high-priority, polled every 5 minutes
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
                "created_at": now,
                "updated_at": now,
            }
        )

    op.bulk_insert(_POLICIES_TABLE, policies)

    op.bulk_insert(
        _BUDGETS_TABLE,
        [
            {
                "id": _BUDGET_ID,
                "provider": "eodhd",
                "max_tokens": 1000,
                "current_tokens": 1000.0,
                "refill_rate_per_second": 10.0,
                "last_refill_at": now,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    for sym, exch in [("AAPL", "US"), ("TSLA", "US"), ("AMZN", "US"), ("BTC-USD", "CC"), ("EURUSD", "FOREX")]:
        _insert_policy("eodhd", "ohlcv", sym, exch, "1h", "", 3600)

    for sym in ["AAPL", "TSLA"]:
        _insert_policy("eodhd", "ohlcv", sym, "US", "5m", "", 300)

    _insert_policy("eodhd", "earnings_calendar", "CALENDAR", "EARNINGS", "", "", 86400)

    for country in ["USA", "EUR", "GBR"]:
        _insert_policy("eodhd", "economic_events", f"EVENTS.{country}", "", "", "", 86400)

    for indicator in ["gdp_current_usd", "inflation_consumer_prices_annual", "unemployment_total_pct"]:
        _insert_policy("eodhd", "macro_indicator", f"USA.{indicator}", "", "", "", 604800)
    for indicator in ["gdp_current_usd", "inflation_consumer_prices_annual"]:
        _insert_policy("eodhd", "macro_indicator", f"EUR.{indicator}", "", "", "", 604800)

    for sym, exch in [("AAPL", "US"), ("TSLA", "US"), ("AMZN", "US"), ("BTC-USD", "CC")]:
        _insert_policy("eodhd", "news_sentiment", sym, exch, "", "", 21600)

    for sym in ["AAPL", "TSLA", "AMZN"]:
        _insert_policy("eodhd", "insider_transactions", sym, "US", "", "", 86400)

    for series in ["UST.yield", "UST.bill", "UST.longterm"]:
        _insert_policy("eodhd", "yield_curve", series, "", "", "", 86400)

    for sym in ["AAPL", "TSLA", "AMZN", "VTI", "BRK-B"]:
        _insert_policy("eodhd", "market_cap", sym, "US", "", "", 604800)


def downgrade() -> None:
    all_policy_ids = _core_policy_ids() + _extended_seed_ids()
    op.execute(_POLICIES_TABLE.delete().where(_POLICIES_TABLE.c.id.in_(all_policy_ids)))
    op.execute(_BUDGETS_TABLE.delete().where(_BUDGETS_TABLE.c.id == _BUDGET_ID))
