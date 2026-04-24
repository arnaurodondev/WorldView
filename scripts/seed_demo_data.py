#!/usr/bin/env python3
"""scripts/seed_demo_data.py — Idempotent demo data seeder for local / staging QA.

WHY THIS EXISTS:
  The worldview platform is event-driven: most data arrives via EODHD API calls,
  NLP pipeline processing, and Kafka event chains. In a fresh local environment
  (or after a volume wipe), all DBs are empty. This script seeds realistic but
  clearly synthetic data so every UI feature can be tested without running the
  full ingestion pipeline.

WHAT IS SEEDED:
  market_data_db   → company_profiles (description + highlights/technicals JSONB),
                     ohlcv_bars (90 simulated daily bars for instruments with <10),
                     fundamental_metrics (daily_return + screener metrics if missing)
  intelligence_db  → canonical_entities (financial instruments + sector/org entities),
                     entity_aliases (ticker aliases), relations (KG graph edges)

WHAT IS NOT RE-SEEDED (already exists from EODHD ingestion):
  securities, instruments, quotes, existing fundamental_metrics

IDEMPOTENCY:
  Every INSERT uses ON CONFLICT DO NOTHING with deterministic UUIDs.
  Running the script multiple times is safe — it will not create duplicates.

USAGE:
  python scripts/seed_demo_data.py              # seed (idempotent)
  python scripts/seed_demo_data.py --reset      # truncate seeded tables then re-seed

ENVIRONMENT VARIABLES (all have sensible defaults for local Docker Compose):
  MARKET_DATA_DB_URL   — default: postgresql://postgres:postgres@localhost:5432/market_data_db
  INTELLIGENCE_DB_URL  — default: postgresql://postgres:postgres@localhost:5432/intelligence_db

REQUIREMENTS:
  psycopg2-binary  (pip install psycopg2-binary)
  OR the shared venv:  .venv312/bin/python scripts/seed_demo_data.py
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta

# ---------------------------------------------------------------------------
# Dependency guard — give a helpful message if psycopg2 is missing
# ---------------------------------------------------------------------------
try:
    import psycopg2  # type: ignore[import-untyped]
    import psycopg2.extras  # type: ignore[import-untyped]
except ImportError:
    print("psycopg2 not found. Install it with:", file=sys.stderr)
    print("  pip install psycopg2-binary", file=sys.stderr)
    print("or run this script via the project venv:", file=sys.stderr)
    print("  .venv312/bin/python scripts/seed_demo_data.py", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MARKET_DATA_DB_URL = os.environ.get(
    "MARKET_DATA_DB_URL",
    "postgresql://postgres:postgres@localhost:5432/market_data_db",
)
INTELLIGENCE_DB_URL = os.environ.get(
    "INTELLIGENCE_DB_URL",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)

# ---------------------------------------------------------------------------
# Target instruments (real data should already exist from EODHD ingestion)
# ---------------------------------------------------------------------------

# Deterministic entity UUIDs for intelligence_db canonical_entities.
# WHY deterministic: idempotent ON CONFLICT DO NOTHING requires stable PKs.
# Prefix "11111111" visually distinguishes demo entities from real UUIDv7 IDs.
INSTRUMENTS: list[dict] = [
    {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "US",
        "sector": "Information Technology",
        "industry": "Technology Hardware & Equipment",
        "gics_sector": "Information Technology",
        "country": "US",
        "currency": "USD",
        "isin": "US0378331005",
        "entity_id": "11111111-0001-7000-8000-000000000001",  # stable KG entity UUID
        "description": (
            "Apple Inc. designs, manufactures, and markets smartphones, personal computers, "
            "tablets, wearables, and accessories worldwide. The Company sells its products "
            "through its retail and online stores, direct sales force, and third-party "
            "cellular network carriers, wholesalers, retailers, and resellers."
        ),
        "highlights": {
            "MarketCapitalization": 3_900_000_000_000,
            "PERatio": 34.6,
            "EarningsShare": 7.89,
            "DividendYield": 0.0039,
            "ProfitMargin": 0.270,
            "ReturnOnEquityTTM": 1.520,
            "RevenueTTM": 435_617_000_000,
        },
        "technicals": {
            "52WeekHigh": 288.35,
            "52WeekLow": 192.41,
            "Beta": 1.109,
            "50DayMA": 220.5,
            "200DayMA": 215.3,
        },
        "seed_ohlcv": True,  # has real bars from EODHD
        "base_price": 195.0,
    },
    {
        "ticker": "MSFT",
        "name": "Microsoft Corporation",
        "exchange": "US",
        "sector": "Information Technology",
        "industry": "Software - Infrastructure",
        "gics_sector": "Information Technology",
        "country": "US",
        "currency": "USD",
        "isin": "US5949181045",
        "entity_id": "11111111-0002-7000-8000-000000000001",
        "description": (
            "Microsoft Corporation develops, licenses, and supports software, services, devices, "
            "and solutions worldwide. The company's Productivity and Business Processes segment "
            "offers Office, Exchange, SharePoint, Microsoft Teams, Azure, and LinkedIn. "
            "Its Intelligent Cloud segment includes server products and cloud services like Azure."
        ),
        "highlights": {
            "MarketCapitalization": 2_700_000_000_000,
            "PERatio": 35.2,
            "EarningsShare": 12.53,
            "DividendYield": 0.0072,
            "ProfitMargin": 0.358,
            "ReturnOnEquityTTM": 0.354,
            "RevenueTTM": 261_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 468.35,
            "52WeekLow": 331.41,
            "Beta": 0.895,
            "50DayMA": 390.5,
            "200DayMA": 410.0,
        },
        "seed_ohlcv": True,
        "base_price": 390.0,
    },
    {
        "ticker": "NVDA",
        "name": "NVIDIA Corporation",
        "exchange": "US",
        "sector": "Information Technology",
        "industry": "Semiconductors",
        "gics_sector": "Information Technology",
        "country": "US",
        "currency": "USD",
        "isin": "US67066G1040",
        "entity_id": "11111111-0003-7000-8000-000000000001",
        "description": (
            "NVIDIA Corporation provides graphics, computing and networking solutions globally. "
            "Its two segments are Graphics and Compute & Networking. The company's products "
            "are used in gaming, professional visualization, datacenter, and automotive markets. "
            "NVIDIA is a key enabler of AI/ML training and inference workloads."
        ),
        "highlights": {
            "MarketCapitalization": 2_200_000_000_000,
            "PERatio": 45.0,
            "EarningsShare": 2.94,
            "DividendYield": 0.0003,
            "ProfitMargin": 0.553,
            "ReturnOnEquityTTM": 1.232,
            "RevenueTTM": 130_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 153.13,
            "52WeekLow": 73.75,
            "Beta": 1.97,
            "50DayMA": 95.3,
            "200DayMA": 110.2,
        },
        "seed_ohlcv": True,
        "base_price": 90.0,
    },
    {
        "ticker": "AMZN",
        "name": "Amazon.com Inc",
        "exchange": "US",
        "sector": "Consumer Cyclical",
        "industry": "Internet Retail",
        "gics_sector": "Consumer Discretionary",
        "country": "US",
        "currency": "USD",
        "isin": "US0231351067",
        "entity_id": "11111111-0004-7000-8000-000000000001",
        "description": (
            "Amazon.com Inc. engages in the retail sale of consumer products and subscriptions "
            "through online and physical stores in North America and internationally. It also "
            "provides Amazon Web Services (AWS), digital advertising services, subscription "
            "services including Amazon Prime, and third-party seller services."
        ),
        "highlights": {
            "MarketCapitalization": 1_900_000_000_000,
            "PERatio": 38.5,
            "EarningsShare": 5.53,
            "DividendYield": 0.0,
            "ProfitMargin": 0.098,
            "ReturnOnEquityTTM": 0.247,
            "RevenueTTM": 630_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 242.52,
            "52WeekLow": 151.61,
            "Beta": 1.22,
            "50DayMA": 195.0,
            "200DayMA": 205.0,
        },
        "seed_ohlcv": False,  # AMZN already has 643 real bars
        "base_price": 205.0,
    },
    {
        "ticker": "TSLA",
        "name": "Tesla Inc",
        "exchange": "US",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "gics_sector": "Consumer Discretionary",
        "country": "US",
        "currency": "USD",
        "isin": "US88160R1014",
        "entity_id": "11111111-0005-7000-8000-000000000001",
        "description": (
            "Tesla, Inc. designs, develops, manufactures, leases, and sells electric vehicles, "
            "energy generation and storage systems, and related services. The company also offers "
            "vehicle insurance, repair services, non-warranty after-sales services, and sells "
            "pre-owned vehicles. Its energy division deploys utility-scale Megapack systems."
        ),
        "highlights": {
            "MarketCapitalization": 700_000_000_000,
            "PERatio": 52.0,
            "EarningsShare": 2.04,
            "DividendYield": 0.0,
            "ProfitMargin": 0.073,
            "ReturnOnEquityTTM": 0.123,
            "RevenueTTM": 97_700_000_000,
        },
        "technicals": {
            "52WeekHigh": 488.54,
            "52WeekLow": 138.80,
            "Beta": 2.29,
            "50DayMA": 240.0,
            "200DayMA": 280.0,
        },
        "seed_ohlcv": True,
        "base_price": 240.0,
    },
    {
        "ticker": "GOOGL",
        "name": "Alphabet Inc Class A",
        "exchange": "US",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "gics_sector": "Communication Services",
        "country": "US",
        "currency": "USD",
        "isin": "US02079K3059",
        "entity_id": "11111111-0006-7000-8000-000000000001",
        "description": (
            "Alphabet Inc. provides various products and platforms worldwide through Google Search, "
            "YouTube, Google Maps, Google Play, Chrome, Android, and Google Cloud. Its segments "
            "include Google Services, Google Cloud, and Other Bets. The company's advertising "
            "platform is the largest in the world by revenue."
        ),
        "highlights": {
            "MarketCapitalization": 1_800_000_000_000,
            "PERatio": 20.5,
            "EarningsShare": 8.04,
            "DividendYield": 0.0,
            "ProfitMargin": 0.262,
            "ReturnOnEquityTTM": 0.312,
            "RevenueTTM": 350_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 207.05,
            "52WeekLow": 140.53,
            "Beta": 1.05,
            "50DayMA": 165.0,
            "200DayMA": 175.0,
        },
        "seed_ohlcv": True,
        "base_price": 165.0,
    },
    {
        "ticker": "META",
        "name": "Meta Platforms Inc.",
        "exchange": "US",
        "sector": "Communication Services",
        "industry": "Internet Content & Information",
        "gics_sector": "Communication Services",
        "country": "US",
        "currency": "USD",
        "isin": "US30303M1027",
        "entity_id": "11111111-0007-7000-8000-000000000001",
        "description": (
            "Meta Platforms, Inc. develops products that enable people to connect and share "
            "through mobile devices, PCs, virtual reality headsets, and wearables worldwide. "
            "The company's products include Facebook, Instagram, Threads, WhatsApp, and the "
            "Meta Quest virtual reality platform. It also provides AI-powered advertising tools."
        ),
        "highlights": {
            "MarketCapitalization": 1_200_000_000_000,
            "PERatio": 25.0,
            "EarningsShare": 21.97,
            "DividendYield": 0.0034,
            "ProfitMargin": 0.373,
            "ReturnOnEquityTTM": 0.386,
            "RevenueTTM": 165_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 740.91,
            "52WeekLow": 434.47,
            "Beta": 1.19,
            "50DayMA": 565.0,
            "200DayMA": 590.0,
        },
        "seed_ohlcv": True,
        "base_price": 565.0,
    },
    {
        "ticker": "JPM",
        "name": "JPMorgan Chase & Co",
        "exchange": "US",
        "sector": "Financial Services",
        "industry": "Banks - Diversified",
        "gics_sector": "Financials",
        "country": "US",
        "currency": "USD",
        "isin": "US46625H1005",
        "entity_id": "11111111-0008-7000-8000-000000000001",
        "description": (
            "JPMorgan Chase & Co. operates as a financial services company worldwide. "
            "Its Consumer & Community Banking segment offers deposit and investment products, "
            "lending, and payment services. The Commercial Banking segment provides lending, "
            "treasury, investment banking, and commercial real estate services."
        ),
        "highlights": {
            "MarketCapitalization": 680_000_000_000,
            "PERatio": 13.5,
            "EarningsShare": 19.75,
            "DividendYield": 0.0215,
            "ProfitMargin": 0.334,
            "ReturnOnEquityTTM": 0.176,
            "RevenueTTM": 215_000_000_000,
        },
        "technicals": {
            "52WeekHigh": 280.25,
            "52WeekLow": 185.78,
            "Beta": 1.11,
            "50DayMA": 242.0,
            "200DayMA": 235.0,
        },
        "seed_ohlcv": True,
        "base_price": 242.0,
    },
]

# Additional KG entities (non-instrument) for richer graph rendering
KG_EXTRA_ENTITIES: list[dict] = [
    {
        "entity_id": "11111111-0101-7000-8000-000000000001",
        "canonical_name": "Artificial Intelligence",
        "entity_type": "technology_theme",
        "ticker": None,
        "exchange": None,
    },
    {
        "entity_id": "11111111-0102-7000-8000-000000000001",
        "canonical_name": "Semiconductor Industry",
        "entity_type": "industry",
        "ticker": None,
        "exchange": None,
    },
    {
        "entity_id": "11111111-0103-7000-8000-000000000001",
        "canonical_name": "Cloud Computing",
        "entity_type": "technology_theme",
        "ticker": None,
        "exchange": None,
    },
    {
        "entity_id": "11111111-0104-7000-8000-000000000001",
        "canonical_name": "Electric Vehicles",
        "entity_type": "technology_theme",
        "ticker": None,
        "exchange": None,
    },
    {
        "entity_id": "11111111-0105-7000-8000-000000000001",
        "canonical_name": "Digital Advertising",
        "entity_type": "technology_theme",
        "ticker": None,
        "exchange": None,
    },
]

# KG relations between demo entities
# (subject_entity_id, canonical_type, object_entity_id, decay_class, confidence)
KG_RELATIONS: list[tuple] = [
    # AAPL relations
    ("11111111-0001-7000-8000-000000000001", "COMPETES_WITH", "11111111-0002-7000-8000-000000000001", "SLOW", 0.85),
    (
        "11111111-0001-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.80,
    ),
    # MSFT relations
    (
        "11111111-0002-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.95,
    ),
    (
        "11111111-0002-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0103-7000-8000-000000000001",
        "MEDIUM",
        0.90,
    ),
    # NVDA relations
    (
        "11111111-0003-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.98,
    ),
    ("11111111-0003-7000-8000-000000000001", "EXPOSED_TO_THEME", "11111111-0102-7000-8000-000000000001", "SLOW", 0.92),
    ("11111111-0003-7000-8000-000000000001", "SUPPLIER_OF", "11111111-0001-7000-8000-000000000001", "SLOW", 0.75),
    # AMZN relations
    (
        "11111111-0004-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0103-7000-8000-000000000001",
        "MEDIUM",
        0.93,
    ),
    ("11111111-0004-7000-8000-000000000001", "COMPETES_WITH", "11111111-0002-7000-8000-000000000001", "SLOW", 0.80),
    # TSLA relations
    (
        "11111111-0005-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0104-7000-8000-000000000001",
        "MEDIUM",
        0.95,
    ),
    (
        "11111111-0005-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.70,
    ),
    # GOOGL relations
    (
        "11111111-0006-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.90,
    ),
    (
        "11111111-0006-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0105-7000-8000-000000000001",
        "MEDIUM",
        0.88,
    ),
    ("11111111-0006-7000-8000-000000000001", "COMPETES_WITH", "11111111-0002-7000-8000-000000000001", "SLOW", 0.82),
    # META relations
    (
        "11111111-0007-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.85,
    ),
    (
        "11111111-0007-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0105-7000-8000-000000000001",
        "MEDIUM",
        0.95,
    ),
    ("11111111-0007-7000-8000-000000000001", "COMPETES_WITH", "11111111-0006-7000-8000-000000000001", "SLOW", 0.88),
    # JPM relations
    (
        "11111111-0008-7000-8000-000000000001",
        "EXPOSED_TO_THEME",
        "11111111-0101-7000-8000-000000000001",
        "MEDIUM",
        0.60,
    ),
]

# Decay alpha values (from intelligence_db decay_class_config)
_DECAY_ALPHA = {
    "FLASH": 0.069315,
    "FAST": 0.023105,
    "MEDIUM": 0.011552,
    "SLOW": 0.003851,
}

# ---------------------------------------------------------------------------
# OHLCV simulation helpers
# ---------------------------------------------------------------------------


def _sim_ohlcv(
    instrument_id: str,
    base_price: float,
    n_days: int = 90,
    seed: int = 42,
) -> list[dict]:
    """Generate n_days of simulated daily OHLCV bars via random-walk.

    Uses a seeded RNG so each instrument gets reproducible data.
    WHY random walk: realistic price series with mean-reversion drift,
    matching what the chart expects (coherent open/high/low/close ordering).
    """
    rng = random.Random(seed)  # noqa: S311 — seeded RNG for reproducible demo data, not security
    bars = []
    today = date.today()
    price = base_price

    # Walk backwards from today — n_days of trading data
    # Skip weekends (approximate; real data has no weekend bars)
    trading_dates = []
    d = today - timedelta(days=1)
    while len(trading_dates) < n_days:
        if d.weekday() < 5:  # Mon-Fri
            trading_dates.append(d)
        d -= timedelta(days=1)
    trading_dates.reverse()

    for bar_date in trading_dates:
        # Random walk: daily return ~ N(0.05%, 1.5%)
        daily_ret = rng.gauss(0.0005, 0.015)
        price_close = price * (1 + daily_ret)
        high = price_close * (1 + abs(rng.gauss(0, 0.008)))
        low = price_close * (1 - abs(rng.gauss(0, 0.008)))
        open_ = price + rng.gauss(0, price * 0.005)
        # Clamp low/high to be sensible relative to open/close
        low = min(low, open_, price_close)
        high = max(high, open_, price_close)
        volume = int(rng.uniform(500_000, 50_000_000))

        bars.append(
            {
                "instrument_id": instrument_id,
                "timeframe": "1d",
                "bar_date": datetime.combine(bar_date, datetime.min.time()).replace(tzinfo=UTC).isoformat(),
                "open": round(open_, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(price_close, 6),
                "volume": volume,
            }
        )
        price = price_close

    return bars


# ---------------------------------------------------------------------------
# Seeding functions
# ---------------------------------------------------------------------------


def _get_instrument_map(cur) -> dict[str, str]:
    """Return {ticker: instrument_id} for all 8 target instruments.

    Looks up by (symbol, exchange) to match real EODHD-ingested data.
    """
    tickers = [i["ticker"] for i in INSTRUMENTS]
    cur.execute(
        "SELECT symbol, id FROM instruments WHERE symbol = ANY(%s) AND exchange = 'US'",
        (tickers,),
    )
    rows = cur.fetchall()
    mapping = {row[0]: str(row[1]) for row in rows}
    print(f"  Found {len(mapping)}/{len(tickers)} instruments in market_data_db")
    return mapping


def _get_ohlcv_counts(cur, instrument_ids: list[str]) -> dict[str, int]:
    """Return {instrument_id: bar_count} for target instruments."""
    if not instrument_ids:
        return {}
    cur.execute(
        """
        SELECT instrument_id::text, COUNT(*)
        FROM ohlcv_bars
        WHERE instrument_id = ANY(%s::uuid[])
        GROUP BY instrument_id
        """,
        (instrument_ids,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def seed_market_data(conn, instrument_map: dict[str, str], *, reset: bool = False) -> None:
    """Seed company_profiles, ohlcv_bars, and key fundamental_metrics."""
    cur = conn.cursor()

    if reset:
        print("  [reset] Truncating seeded market_data tables...")
        # Only truncate company_profiles (seeded by this script).
        # ohlcv_bars and fundamental_metrics contain real EODHD data — do NOT wipe.
        cur.execute(
            "DELETE FROM company_profiles WHERE instrument_id = ANY(%s::uuid[])",
            (list(instrument_map.values()),),
        )
        conn.commit()

    # ── 1. Company profiles (description + EODHD-shape data JSONB) ─────────────
    print("  Seeding company_profiles...")
    now_ts = datetime.now(tz=UTC).isoformat()

    for inst in INSTRUMENTS:
        ticker = inst["ticker"]
        instrument_id = instrument_map.get(ticker)
        if not instrument_id:
            print(f"    SKIP {ticker}: not found in market_data_db")
            continue

        # Build EODHD-shape General section JSONB.
        # WHY this shape: S9's get_company_overview extracts profile_data keys
        # (Name, Description, Currency, GicSector, etc.) from company_profiles.data.
        data_jsonb = json.dumps(
            {
                "Name": inst["name"],
                "Description": inst["description"],
                "Currency": inst["currency"],
                "CountryISO": inst["country"],
                "ISIN": inst["isin"],
                "GicSector": inst["gics_sector"],
                "GicGroup": inst["industry"],
                "Highlights": inst["highlights"],
                "Technicals": inst["technicals"],
            }
        )

        cur.execute(
            """
            INSERT INTO company_profiles (instrument_id, description, data, ingested_at)
            VALUES (%s::uuid, %s, %s::jsonb, %s)
            ON CONFLICT (instrument_id) DO NOTHING
            """,
            (instrument_id, inst["description"], data_jsonb, now_ts),
        )
        print(f"    {ticker}: company profile {'inserted' if cur.rowcount else 'already exists'}")

    conn.commit()

    # ── 2. OHLCV bars (only for instruments with <10 real bars) ────────────────
    print("  Seeding ohlcv_bars for instruments with sparse data...")
    ohlcv_counts = _get_ohlcv_counts(cur, list(instrument_map.values()))

    for inst in INSTRUMENTS:
        ticker = inst["ticker"]
        instrument_id = instrument_map.get(ticker)
        if not instrument_id:
            continue

        bar_count = ohlcv_counts.get(instrument_id, 0)
        if bar_count >= 10 and not inst.get("seed_ohlcv", False):
            print(f"    {ticker}: skipping ({bar_count} real bars already exist)")
            continue
        if bar_count >= 90:
            print(f"    {ticker}: skipping ({bar_count} bars >= 90 threshold)")
            continue

        # Generate seed=42+ticker_hash for per-instrument reproducibility
        seed = 42 + hash(ticker) % 1000
        bars = _sim_ohlcv(instrument_id, inst["base_price"], n_days=90, seed=seed)

        inserted = 0
        for bar in bars:
            cur.execute(
                """
                INSERT INTO ohlcv_bars
                  (instrument_id, timeframe, bar_date, open, high, low, close, volume, source, provider_priority)
                VALUES (%s::uuid, %s, %s::timestamptz, %s, %s, %s, %s, %s, 'seed_demo', 0)
                ON CONFLICT (instrument_id, timeframe, bar_date) DO NOTHING
                """,
                (
                    instrument_id,
                    bar["timeframe"],
                    bar["bar_date"],
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar["volume"],
                ),
            )
            inserted += cur.rowcount

        conn.commit()
        print(f"    {ticker}: inserted {inserted}/{len(bars)} bars ({bar_count} pre-existing)")

    # ── 3. Key fundamental_metrics (daily_return) ───────────────────────────────
    # The screener uses daily_return to sort top movers. If not present, results
    # will be empty. We seed it from the highlights data (simulated).
    print("  Seeding daily_return fundamental metric...")
    today_str = date.today().isoformat()

    for inst in INSTRUMENTS:
        ticker = inst["ticker"]
        instrument_id = instrument_map.get(ticker)
        if not instrument_id:
            continue

        # Check if daily_return already exists for today
        cur.execute(
            """
            SELECT COUNT(*) FROM fundamental_metrics
            WHERE instrument_id=%s::uuid AND metric='daily_return' AND as_of_date=%s
            """,
            (instrument_id, today_str),
        )
        if cur.fetchone()[0] > 0:
            print(f"    {ticker}: daily_return already exists for today")
            continue

        # Simulate a daily return (bounded realistic range)
        seed = 42 + hash(ticker + today_str) % 1000
        rng = random.Random(seed)  # noqa: S311 — seeded RNG for reproducible demo data, not security
        daily_ret = rng.gauss(0.0008, 0.018)  # ~+0.08% mean, 1.8% std
        daily_ret = max(-0.10, min(0.10, daily_ret))  # clamp to ±10%

        cur.execute(
            """
            INSERT INTO fundamental_metrics
              (instrument_id, as_of_date, metric, value_numeric, period_type, section)
            VALUES (%s::uuid, %s, 'daily_return', %s, 'daily', 'technicals')
            ON CONFLICT (instrument_id, as_of_date, metric, period_type) DO NOTHING
            """,
            (instrument_id, today_str, round(daily_ret, 6)),
        )
        print(f"    {ticker}: daily_return={daily_ret:.4f} {'inserted' if cur.rowcount else 'conflict'}")

    conn.commit()
    cur.close()


def seed_intelligence_db(conn_intel, instrument_map: dict[str, str], *, reset: bool = False) -> None:
    """Seed canonical_entities, entity_aliases, and relations in intelligence_db."""
    cur = conn_intel.cursor()
    now_ts = datetime.now(tz=UTC).isoformat()

    if reset:
        print("  [reset] Removing demo entities from intelligence_db...")
        demo_entity_ids = [i["entity_id"] for i in INSTRUMENTS] + [e["entity_id"] for e in KG_EXTRA_ENTITIES]
        cur.execute(
            "DELETE FROM canonical_entities WHERE entity_id = ANY(%s::uuid[])",
            (demo_entity_ids,),
        )
        conn_intel.commit()

    # ── 1. Canonical entities (financial instruments) ──────────────────────────
    print("  Seeding canonical_entities (financial instruments)...")
    for inst in INSTRUMENTS:
        metadata = json.dumps(
            {
                "instrument_id": instrument_map.get(inst["ticker"]),  # link back to market_data_db
                "gics_sector": inst["gics_sector"],
                "country": inst["country"],
            }
        )
        cur.execute(
            """
            INSERT INTO canonical_entities
              (entity_id, canonical_name, entity_type, ticker, exchange, metadata, created_at, updated_at)
            VALUES (%s::uuid, %s, 'financial_instrument', %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (entity_id) DO NOTHING
            """,
            (
                inst["entity_id"],
                inst["name"],
                inst["ticker"],
                inst["exchange"],
                metadata,
                now_ts,
                now_ts,
            ),
        )
        print(f"    {inst['ticker']}: {'inserted' if cur.rowcount else 'already exists'}")

    # ── 2. Additional KG theme/industry entities ────────────────────────────────
    print("  Seeding KG theme entities...")
    for ent in KG_EXTRA_ENTITIES:
        cur.execute(
            """
            INSERT INTO canonical_entities
              (entity_id, canonical_name, entity_type, ticker, exchange, created_at, updated_at)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_id) DO NOTHING
            """,
            (
                ent["entity_id"],
                ent["canonical_name"],
                ent["entity_type"],
                ent["ticker"],
                ent["exchange"],
                now_ts,
                now_ts,
            ),
        )
        print(f"    {ent['canonical_name']}: {'inserted' if cur.rowcount else 'already exists'}")

    conn_intel.commit()

    # ── 3. Entity aliases (ticker aliases for search/NER lookup) ───────────────
    print("  Seeding entity_aliases...")
    for inst in INSTRUMENTS:
        ticker = inst["ticker"]
        alias_text = ticker
        normalized = ticker.upper()
        # EXACT aliases must be unique (uidx_entity_aliases_normalized filters on alias_type+is_active)
        cur.execute(
            """
            INSERT INTO entity_aliases
              (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source, created_at)
            VALUES (%s::uuid, %s, %s, 'TICKER', true, 'seed_demo', %s)
            ON CONFLICT DO NOTHING
            """,
            (inst["entity_id"], alias_text, normalized, now_ts),
        )
        print(f"    {ticker}: alias {'inserted' if cur.rowcount else 'already exists'}")

    conn_intel.commit()

    # ── 4. Relations (KG edges) ─────────────────────────────────────────────────
    print("  Seeding KG relations...")
    for subject_eid, rel_type, object_eid, decay_class, confidence in KG_RELATIONS:
        decay_alpha = _DECAY_ALPHA.get(decay_class, 0.011552)
        # WHY no partition_key: it's GENERATED ALWAYS AS STORED — must NOT be in INSERT
        cur.execute(
            """
            INSERT INTO relations
              (subject_entity_id, canonical_type, object_entity_id,
               semantic_mode, decay_class, decay_alpha, base_confidence,
               confidence, confidence_stale, first_evidence_at, latest_evidence_at,
               evidence_count, relation_period_type, strongest_contra_score,
               contra_count_by_type, contra_stale, summary_stale, created_at)
            VALUES
              (%s::uuid, %s, %s::uuid,
               'RELATION_STATE', %s, %s, %s,
               %s, false, %s, %s,
               1, 'ONGOING', 0.0,
               '{}'::jsonb, false, true, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                subject_eid,
                rel_type,
                object_eid,
                decay_class,
                decay_alpha,
                confidence,
                confidence,
                now_ts,
                now_ts,
                now_ts,
            ),
        )
        print(f"    {rel_type}: {subject_eid[:8]}… → {object_eid[:8]}… {'inserted' if cur.rowcount else 'conflict'}")

    conn_intel.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_seeding(conn_mkt, conn_intel, instrument_map: dict[str, str]) -> bool:
    """Print a summary table and return True if all required data is present."""
    cur_mkt = conn_mkt.cursor()
    cur_intel = conn_intel.cursor()

    print("\n─── Validation ───────────────────────────────────────────────────────")

    all_ok = True
    for inst in INSTRUMENTS:
        ticker = inst["ticker"]
        iid = instrument_map.get(ticker)

        # company_profile
        cur_mkt.execute("SELECT COUNT(*) FROM company_profiles WHERE instrument_id=%s::uuid", (iid,))
        has_profile = cur_mkt.fetchone()[0] > 0

        # ohlcv bars
        cur_mkt.execute("SELECT COUNT(*) FROM ohlcv_bars WHERE instrument_id=%s::uuid", (iid,))
        n_bars = cur_mkt.fetchone()[0]

        # daily_return
        cur_mkt.execute(
            "SELECT COUNT(*) FROM fundamental_metrics WHERE instrument_id=%s::uuid AND metric='daily_return'",
            (iid,),
        )
        has_daily_return = cur_mkt.fetchone()[0] > 0

        # KG entity
        cur_intel.execute(
            "SELECT COUNT(*) FROM canonical_entities WHERE entity_id=%s::uuid",
            (inst["entity_id"],),
        )
        has_entity = cur_intel.fetchone()[0] > 0

        ok = has_profile and n_bars >= 10 and has_daily_return and has_entity
        status = "✓" if ok else "✗"
        print(
            f"  {status} {ticker:6s} | profile={has_profile} | bars={n_bars:3d}"
            f" | daily_return={has_daily_return} | kg_entity={has_entity}"
        )
        if not ok:
            all_ok = False

    # Relations count
    entity_ids = [i["entity_id"] for i in INSTRUMENTS]
    cur_intel.execute(
        "SELECT COUNT(*) FROM relations WHERE subject_entity_id = ANY(%s::uuid[])",
        (entity_ids,),
    )
    n_relations = cur_intel.fetchone()[0]
    print(f"  KG relations seeded: {n_relations} (expected ≥ {len(KG_RELATIONS)})")

    cur_mkt.close()
    cur_intel.close()
    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for worldview local/staging QA.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete previously seeded rows before re-seeding (idempotent tables only).",
    )
    args = parser.parse_args()

    print("=== worldview demo data seeder ===")
    print(f"  market_data_db : {MARKET_DATA_DB_URL}")
    print(f"  intelligence_db: {INTELLIGENCE_DB_URL}")
    print(f"  reset mode     : {args.reset}")
    print()

    try:
        conn_mkt = psycopg2.connect(MARKET_DATA_DB_URL)
        conn_intel = psycopg2.connect(INTELLIGENCE_DB_URL)
    except Exception as e:
        print(f"ERROR: could not connect to databases: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Discover real instrument IDs from market_data_db
        cur = conn_mkt.cursor()
        instrument_map = _get_instrument_map(cur)
        cur.close()

        if not instrument_map:
            print(
                "WARNING: No target instruments found in market_data_db.\n"
                "Make sure the platform is running and EODHD ingestion has completed.\n"
                "Continuing anyway to seed intelligence_db entities...",
                file=sys.stderr,
            )

        print("\n── market_data_db ─────────────────────────────────────────────────────")
        seed_market_data(conn_mkt, instrument_map, reset=args.reset)

        print("\n── intelligence_db ────────────────────────────────────────────────────")
        seed_intelligence_db(conn_intel, instrument_map, reset=args.reset)

        ok = validate_seeding(conn_mkt, conn_intel, instrument_map)
        print()
        if ok:
            print("✓ All validation checks passed. Demo data is ready.")
        else:
            print("✗ Some validation checks failed. Check output above.")
            sys.exit(1)

    finally:
        conn_mkt.close()
        conn_intel.close()


if __name__ == "__main__":
    main()
