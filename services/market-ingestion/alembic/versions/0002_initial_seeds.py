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


_SEED_IDS = [f"01HXSEED{str(i).zfill(18)}" for i in range(1, 32)]

_SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "US"),
    ("TSLA", "US"),
    ("VTI", "US"),
    ("AMZN", "US"),
    ("BTC-USD", "CC"),
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
    idx = 0

    for symbol, exchange in _SYMBOLS:
        policies.append(
            {
                "id": _SEED_IDS[idx],
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
        idx += 1

        for tf, base_int, prio in [("1d", 21600, 5), ("1w", 43200, 4), ("1mo", 86400, 3)]:
            policies.append(
                {
                    "id": _SEED_IDS[idx],
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
            idx += 1

        policies.append(
            {
                "id": _SEED_IDS[idx],
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
        idx += 1

    op.bulk_insert(_POLICIES_TABLE, policies)

    op.bulk_insert(
        _BUDGETS_TABLE,
        [
            {
                "id": _SEED_IDS[30],
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
    core_policy_ids = _SEED_IDS[:30]
    extended_policy_ids = _extended_seed_ids()
    op.execute(_POLICIES_TABLE.delete().where(_POLICIES_TABLE.c.id.in_(core_policy_ids + extended_policy_ids)))
    op.execute(_BUDGETS_TABLE.delete().where(_BUDGETS_TABLE.c.id == _SEED_IDS[30]))
