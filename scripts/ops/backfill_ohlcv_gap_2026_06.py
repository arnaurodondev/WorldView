"""Backfill the 2026-06 daily-bar ingestion gap directly from EODHD.

Backend-gaps wave 3 (2026-06-11), audit `2026-06-11-fullstack-rework-waves.md`
item 7 ("daily bars 06-04→06-10 missing, quotes stale").

ROOT CAUSE (operational finding, market-ingestion owns the code fix):
  * `MARKET_INGESTION_ROUTING_OHLCV_EOD` routes daily-EOD fetches to the
    `yahoo_finance` adapter, which queries yfinance with the EODHD-style
    ticker ``{symbol}.{exchange}`` (e.g. ``AAPL.US``). Yahoo does not know
    that notation → "possibly delisted; no timezone found" → 0 bars.
  * The task is still reported ``succeeded`` (row_count=0) and the
    watermark's ``last_success_bar_ts`` advances anyway, so the gap NEVER
    self-heals — every scheduler tick fetches only [today, tomorrow).
  * The admin backfill endpoint (POST /api/v1/ingest/backfill) is routed
    through the same cache and silently returns 0 rows too (verified live
    2026-06-11: AAPL backfill task succeeded, fetched_by=yahoo_finance,
    0 bars written).

This script bypasses the broken routing by fetching EODHD daily bars
directly (the key works — fundamentals tasks use it successfully) and
upserting into ``ohlcv_bars`` with the same ON CONFLICT/priority-guard
semantics as ``PgOHLCVRepository.bulk_upsert_with_priority`` — identical
approach to the established ``scripts/ops/backfill_ohlcv_etfs.py``.

Universe: every instrument with ``has_ohlcv = true`` on exchanges US/INDX
(crypto + forex are healthy via the Alpaca 1m → resampling path).
Per-instrument window: from the day AFTER its latest authoritative
(non-derived) 1d bar — clamped to no earlier than ``BACKFILL_FLOOR``
(default 2026-05-01) — through ``BACKFILL_END`` (default 2026-06-10, the
last fully closed US session at the time of writing).

Usage::

    python -m scripts.ops.backfill_ohlcv_gap_2026_06

Environment variables:
    MARKET_DATA_DSN  : asyncpg DSN (default postgres@localhost:5432/market_data_db)
    EODHD_API_KEY    : EODHD key (falls back to reading the worker container env)
    EODHD_BASE_URL   : default https://eodhd.com/api
    BACKFILL_FLOOR   : earliest from-date (default 2026-05-01)
    BACKFILL_END     : last date to fetch (default 2026-06-10)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import asyncpg
import httpx

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/market_data_db"
# Matches the priority the EODHD path writes through the normal Kafka consumer
# (verified: SELECT DISTINCT source, provider_priority FROM ohlcv_bars → eodhd=80).
_EODHD_PROVIDER_PRIORITY = 80
# 8 concurrent EODHD requests keeps us far inside the paid-tier 1000 req/min cap
# while finishing ~600 symbols in well under two minutes.
_HTTP_CONCURRENCY = 8

_UPSERT_SQL = """
    INSERT INTO ohlcv_bars
        (instrument_id, timeframe, bar_date,
         open, high, low, close, volume, adjusted_close,
         source, provider_priority, is_derived, is_partial)
    VALUES ($1, '1d', $2, $3, $4, $5, $6, $7, $8, 'eodhd', $9, false, false)
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
        is_derived = EXCLUDED.is_derived,
        is_partial = EXCLUDED.is_partial
    WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority
"""


def _resolve_api_key() -> str:
    """Return the EODHD key from env, falling back to the worker container."""
    key = os.environ.get("EODHD_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(  # — local dev tooling
            [
                "docker",
                "exec",
                "worldview-market-ingestion-worker-1",
                "printenv",
                "MARKET_INGESTION_EODHD_API_KEY",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


async def _fetch_symbol(
    http: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    symbol: str,
    exchange: str,
    from_date: str,
    to_date: str,
    api_key: str,
    base_url: str,
) -> list[dict]:
    """Fetch daily EOD bars for one symbol; empty list on any failure."""
    params = {"api_token": api_key, "fmt": "json", "period": "d", "from": from_date, "to": to_date}
    async with sem:
        try:
            resp = await http.get(f"{base_url}/eod/{symbol}.{exchange}", params=params)
        except httpx.RequestError as exc:
            print(f"  [WARN] {symbol}.{exchange}: request error {exc}", file=sys.stderr)
            return []
        if resp.status_code == 429:
            await asyncio.sleep(10)
            resp = await http.get(f"{base_url}/eod/{symbol}.{exchange}", params=params)
        if resp.status_code != 200:
            print(f"  [WARN] {symbol}.{exchange}: HTTP {resp.status_code}")
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        return data if isinstance(data, list) else []


def _parse_records(instrument_id: str, raw_bars: list[dict]) -> list[tuple]:
    """Parse EODHD bar dicts into executemany tuples, skipping malformed rows."""
    records: list[tuple] = []
    for raw in raw_bars:
        try:
            bar_date = datetime.strptime(raw["date"], "%Y-%m-%d").replace(tzinfo=UTC)
            records.append(
                (
                    instrument_id,
                    bar_date,
                    Decimal(str(raw["open"])),
                    Decimal(str(raw["high"])),
                    Decimal(str(raw["low"])),
                    Decimal(str(raw["close"])),
                    int(raw.get("volume") or 0),
                    Decimal(str(raw.get("adjusted_close") or raw["close"])),
                    _EODHD_PROVIDER_PRIORITY,
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            print(f"    [SKIP] malformed bar {raw!r}: {exc}", file=sys.stderr)
    return records


async def main() -> None:
    dsn = os.environ.get("MARKET_DATA_DSN", _DEFAULT_DSN)
    base_url = os.environ.get("EODHD_BASE_URL", "https://eodhd.com/api")
    floor = os.environ.get("BACKFILL_FLOOR", "2026-05-01")
    to_date = os.environ.get("BACKFILL_END", "2026-06-10")
    api_key = _resolve_api_key()
    if not api_key:
        print("[ERROR] EODHD_API_KEY unavailable", file=sys.stderr)
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        # Per-instrument window start = day after the latest NON-derived 1d bar
        # (derived bars come from intraday resampling and may be partial — we
        # want authoritative EODHD closes for the whole gap). Instruments whose
        # authoritative history is already current are skipped.
        rows = await pool.fetch(
            """
            SELECT i.id, i.symbol, i.exchange,
                   max(o.bar_date) FILTER (WHERE o.source = 'eodhd') AS latest_eodhd
            FROM instruments i
            LEFT JOIN ohlcv_bars o
                   ON o.instrument_id = i.id AND o.timeframe = '1d'
            WHERE i.has_ohlcv AND i.exchange IN ('US', 'INDX')
            GROUP BY i.id, i.symbol, i.exchange
            """
        )
        end_d = datetime.strptime(to_date, "%Y-%m-%d").date()
        floor_d = datetime.strptime(floor, "%Y-%m-%d").date()

        plan: list[tuple[str, str, str, str]] = []  # (id, symbol, exchange, from)
        for r in rows:
            latest = r["latest_eodhd"].date() if r["latest_eodhd"] else None
            start_d = max(floor_d, latest + timedelta(days=1)) if latest else floor_d
            if start_d > end_d:
                continue  # already current
            plan.append((str(r["id"]), r["symbol"], r["exchange"], start_d.isoformat()))

        print(f"[INFO] gap backfill → {to_date}; {len(plan)}/{len(rows)} instruments need bars")

        sem = asyncio.Semaphore(_HTTP_CONCURRENCY)
        total_bars = 0
        fetched_syms = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:

            async def _one(iid: str, symbol: str, exchange: str, from_date: str) -> int:
                raw = await _fetch_symbol(http, sem, symbol, exchange, from_date, to_date, api_key, base_url)
                records = _parse_records(iid, raw)
                if not records:
                    return 0
                async with pool.acquire() as conn:
                    await conn.executemany(_UPSERT_SQL, records)
                return len(records)

            results = await asyncio.gather(
                *(_one(iid, sym, exch, frm) for iid, sym, exch, frm in plan),
                return_exceptions=True,
            )
        failures = 0
        for (_iid, sym, _exch, _frm), res in zip(plan, results, strict=True):
            if isinstance(res, BaseException):
                failures += 1
                print(f"  [ERROR] {sym}: {res}", file=sys.stderr)
            elif res:
                total_bars += res
                fetched_syms += 1

        print(
            f"[DONE] upserted {total_bars} bars across {fetched_syms} instruments "
            f"({failures} failures, {len(plan) - fetched_syms - failures} symbols returned no data)"
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
