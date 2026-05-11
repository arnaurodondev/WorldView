"""Backfill EODHD daily OHLCV bars for held ETFs missing from market_data_db.

PLAN-0088 Phase 1 — equity-curve backfill (2026-05-10).

Symptom: the portfolio equity curve is a flat horizontal line because
``portfolio_snapshot_worker`` queries ``market-data /api/v1/ohlcv/`` for each
held instrument to compute daily portfolio value, and ALL 11 held ETFs have
``has_ohlcv=false`` (0 bars in ``ohlcv_bars``). The equity-curve chart
therefore never gets any historical valuation points.

Fix: fetch 252 trading days (≈ 1 calendar year) of daily EODHD EOD bars for
each ETF and INSERT them into ``ohlcv_bars`` directly via asyncpg (same
approach as the other ``scripts/ops/backfill_*`` scripts).  Also set
``has_ohlcv=true`` so the ingestion scheduler won't skip these symbols in
future refresh cycles.

The 11 ETFs that are held (confirmed from portfolio_db.holdings on 2026-05-10):
    XLE, MSTR, QQQ, PPA, XLK, TLT, IEF, IBIT, VTV, XLV, XLY

Usage::

    # From repo root with .venv312 active (or any env with httpx + asyncpg):
    python -m scripts.ops.backfill_ohlcv_etfs

    # Override the DSN or EODHD key via env vars:
    MARKET_DATA_DSN=postgresql://... EODHD_API_KEY=xxx python -m scripts.ops.backfill_ohlcv_etfs

Environment variables:
    MARKET_DATA_DSN   : asyncpg DSN for market_data_db
                        default = postgresql://postgres:postgres@localhost:5432/market_data_db
    EODHD_API_KEY     : EODHD API key (required — no default)
    EODHD_BASE_URL    : EODHD REST base URL
                        default = https://eodhd.com/api
    BACKFILL_START    : ISO date to fetch from (default = 365 calendar days ago)
    BACKFILL_END      : ISO date to fetch to   (default = today)
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import asyncpg
import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

# asyncpg does NOT accept the "+asyncpg" driver suffix that SQLAlchemy uses.
# Strip it so the script works out-of-the-box without a separate .env.
_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/market_data_db"

# The 11 ETF instruments held in portfolio_db on 2026-05-10.
# key = EODHD symbol (what we query), value = (instrument_id, exchange) pair.
# UUIDs come from market_data_db.instruments as of 2026-05-10.
_ETF_INSTRUMENTS: dict[str, tuple[str, str]] = {
    "XLE": ("019e0db5-f577-70ff-8fc0-d2443e9f7dcf", "US"),
    "MSTR": ("019e0db6-2e39-7e04-aaf8-9ec675797470", "US"),
    "QQQ": ("019e0db6-80be-728f-a1e0-a0ef6a0aae32", "US"),
    "PPA": ("019e0db6-c362-758d-b83e-d957a0530a67", "US"),
    "XLK": ("019e0db9-4214-7fdf-b127-36770a801911", "US"),
    "TLT": ("019e0db9-4dd4-7a0e-ae2c-df5d6a5246ef", "US"),
    "IEF": ("019e0dbd-e1ad-7bd8-bc99-725e861e0086", "US"),
    "IBIT": ("019e0dbe-d0a5-76c0-8821-fb229e4a4c6e", "US"),
    "VTV": ("019e0dbf-30b1-7bb1-9f6f-bb51b6d93be9", "US"),
    "XLV": ("019e0dbf-5fbf-754d-8a97-de25af8bd858", "US"),
    "XLY": ("019e0dbf-830c-793b-be2b-ed702f1c589b", "US"),
}

# Provider priority for EODHD daily bars (matches the market-ingestion adapter).
# Lower number = higher priority (80 = EODHD OHLCV tier, see EODHD_CREDIT_COST).
_EODHD_PROVIDER_PRIORITY = 80


# ── EODHD fetch ───────────────────────────────────────────────────────────────


async def _fetch_eodhd_eod(
    client: httpx.AsyncClient,
    symbol: str,
    exchange: str,
    from_date: str,
    to_date: str,
    api_key: str,
    base_url: str,
) -> list[dict]:
    """Fetch daily EOD bars from EODHD for ``{symbol}.{exchange}``.

    Returns a list of raw bar dicts (may be empty if the symbol is not found
    or no data exists in the requested range).

    WHY asyncio.sleep between requests: EODHD's free + standard tiers limit
    concurrent requests; a 300 ms inter-request delay keeps us well inside
    the 1 req/s soft limit for daily bar fetches.
    """
    ticker = f"{symbol}.{exchange}"
    url = f"{base_url}/eod/{ticker}"
    params = {
        "api_token": api_key,
        "fmt": "json",
        "period": "d",
        "from": from_date,
        "to": to_date,
    }
    try:
        resp = await client.get(url, params=params)
    except httpx.RequestError as exc:
        print(f"  [WARN] {symbol}: HTTP request error — {exc}", file=sys.stderr)
        return []

    if resp.status_code == 404:
        print(f"  [WARN] {symbol}: EODHD returned 404 (symbol not found on exchange {exchange})")
        return []
    if resp.status_code == 429:
        print(f"  [WARN] {symbol}: EODHD rate-limited (429) — pausing 10s before retry")
        await asyncio.sleep(10)
        # Single retry
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            print(f"  [ERROR] {symbol}: retry also failed with HTTP {resp.status_code}")
            return []
    if resp.status_code != 200:
        print(f"  [ERROR] {symbol}: unexpected HTTP {resp.status_code}")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"  [ERROR] {symbol}: JSON parse failure — {exc}", file=sys.stderr)
        return []

    if not isinstance(data, list):
        print(f"  [WARN] {symbol}: EODHD returned non-list payload (type={type(data).__name__})")
        return []

    return data


# ── DB upsert ─────────────────────────────────────────────────────────────────


async def _upsert_bars(
    conn: asyncpg.Connection,
    instrument_id: str,
    bars: list[dict],
) -> int:
    """Bulk-upsert parsed daily OHLCV rows into ``ohlcv_bars``.

    Uses the same ON CONFLICT / priority-guard semantics as
    ``PgOHLCVRepository.bulk_upsert_with_priority``:

        ON CONFLICT (instrument_id, timeframe, bar_date)
        DO UPDATE ... WHERE EXCLUDED.provider_priority >= existing.provider_priority

    Returns the number of rows successfully parsed and upserted.
    """
    if not bars:
        return 0

    # Parse and validate each row; skip rows that can't be parsed.
    records: list[tuple] = []
    for raw in bars:
        try:
            # EODHD EOD format:
            #   { "date": "2025-01-02", "open": 123.4, "high": 125.0,
            #     "low": 122.1, "close": 124.5, "adjusted_close": 124.5,
            #     "volume": 1234567 }
            bar_date = datetime.strptime(raw["date"], "%Y-%m-%d").replace(tzinfo=UTC)
            open_ = Decimal(str(raw["open"]))
            high = Decimal(str(raw["high"]))
            low = Decimal(str(raw["low"]))
            close = Decimal(str(raw["close"]))
            adj = Decimal(str(raw.get("adjusted_close") or raw["close"]))
            volume = int(raw.get("volume") or 0)
        except (KeyError, ValueError, InvalidOperation) as exc:
            print(f"    [SKIP] malformed bar row {raw!r}: {exc}", file=sys.stderr)
            continue

        records.append(
            (
                instrument_id,
                "1d",  # timeframe
                bar_date,
                open_,
                high,
                low,
                close,
                volume,
                adj,  # adjusted_close
                "eodhd",  # source
                _EODHD_PROVIDER_PRIORITY,
                False,  # is_derived
                False,  # is_partial
            )
        )

    if not records:
        return 0

    # asyncpg executemany with a raw SQL upsert.
    # TimescaleDB hyper-table: insert goes through the normal INSERT path;
    # ON CONFLICT resolves against the composite PK (instrument_id, timeframe, bar_date).
    # WHY EXCLUDED.provider_priority >= ohlcv_bars.provider_priority:
    #   guards against a future higher-priority provider overwrite being
    #   accidentally replaced by this lower-priority script re-run.
    sql = """
        INSERT INTO ohlcv_bars
            (instrument_id, timeframe, bar_date,
             open, high, low, close, volume, adjusted_close,
             source, provider_priority, is_derived, is_partial)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        ON CONFLICT (instrument_id, timeframe, bar_date)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low  = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            adjusted_close = EXCLUDED.adjusted_close,
            source = EXCLUDED.source,
            provider_priority = EXCLUDED.provider_priority,
            is_partial = EXCLUDED.is_partial
        WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority
    """
    await conn.executemany(sql, records)
    return len(records)


async def _mark_has_ohlcv(conn: asyncpg.Connection, instrument_id: str) -> None:
    """Set ``has_ohlcv = true`` on the instrument row."""
    await conn.execute(
        "UPDATE instruments SET has_ohlcv = true WHERE id = $1",
        instrument_id,
    )


# ── Main orchestrator ─────────────────────────────────────────────────────────


async def main() -> None:
    # -- Config from env
    dsn = os.environ.get("MARKET_DATA_DSN", _DEFAULT_DSN)
    api_key = os.environ.get("EODHD_API_KEY", "")
    base_url = os.environ.get("EODHD_BASE_URL", "https://eodhd.com/api")

    if not api_key:
        # Try to read from the docker container if running locally
        print("[INFO] EODHD_API_KEY not set in env — attempting to read from market-ingestion container")
        try:
            import subprocess

            result = subprocess.run(
                ["docker", "exec", "worldview-market-ingestion-1", "printenv", "MARKET_INGESTION_EODHD_API_KEY"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            api_key = result.stdout.strip()
        except Exception as exc:
            print(f"[DEBUG] could not read key from container: {exc}")  # non-fatal

    if not api_key:
        print(
            "[ERROR] EODHD_API_KEY is required. Set it as an env var or ensure the market-ingestion container is running.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Date range: 365 calendar days back → today (includes ≈252 trading days)
    today = date.today()
    default_from = (today - timedelta(days=365)).isoformat()
    default_to = today.isoformat()
    from_date = os.environ.get("BACKFILL_START", default_from)
    to_date = os.environ.get("BACKFILL_END", default_to)

    print(f"[INFO] OHLCV ETF backfill: {from_date} → {to_date} ({len(_ETF_INSTRUMENTS)} symbols)")
    print(f"[INFO] DB: {dsn.split('@')[-1]}")  # only print host/db, not credentials

    # -- Connect to DB
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        # -- HTTP client (BP-235: explicit timeout)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            results: dict[str, int] = {}
            errors: list[str] = []

            for symbol, (instrument_id, exchange) in _ETF_INSTRUMENTS.items():
                print(f"  Fetching {symbol}.{exchange} ...")
                raw_bars = await _fetch_eodhd_eod(
                    http,
                    symbol,
                    exchange,
                    from_date,
                    to_date,
                    api_key,
                    base_url,
                )
                if not raw_bars:
                    print("    → 0 bars returned from EODHD")
                    errors.append(symbol)
                    results[symbol] = 0
                    # Throttle even on empty responses to avoid hammering the API
                    await asyncio.sleep(0.5)
                    continue

                count = await _upsert_bars(conn, instrument_id, raw_bars)
                if count > 0:
                    await _mark_has_ohlcv(conn, instrument_id)

                print(f"    → {len(raw_bars)} raw bars from EODHD, {count} upserted, has_ohlcv=true")
                results[symbol] = count

                # Polite delay between symbols to stay within EODHD rate limits
                await asyncio.sleep(0.4)

    finally:
        await conn.close()

    # -- Summary
    total_bars = sum(results.values())
    print(f"\n[DONE] Total bars upserted: {total_bars}")
    if errors:
        print(f"[WARN] Symbols with 0 bars (check coverage): {', '.join(errors)}")

    # -- Verify
    print("\n[VERIFY] Bar counts per symbol in ohlcv_bars:")
    verify_conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        rows = await verify_conn.fetch(
            """
            SELECT i.symbol, COUNT(o.bar_date) as bar_count
            FROM instruments i
            LEFT JOIN ohlcv_bars o ON o.instrument_id = i.id AND o.timeframe = '1d'
            WHERE i.symbol = ANY($1::text[])
            GROUP BY i.symbol
            ORDER BY i.symbol
            """,
            list(_ETF_INSTRUMENTS.keys()),
        )
        for row in rows:
            print(f"  {row['symbol']:8s}: {row['bar_count']} bars")
    finally:
        await verify_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
