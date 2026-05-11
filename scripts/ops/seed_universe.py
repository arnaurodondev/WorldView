#!/usr/bin/env python3
"""Seed ticker universe: S&P 500 + sector ETFs + top-30 crypto + top-30 macro indicators.

FR-T0-2 (spec-0034 §FR-T0-2) — expand from ~80 to ≥600 instruments.

HOW IT WORKS:
  1. Load infra/seeds/universe.json — the canonical seed list.
  2. Connect to market_data_db via asyncpg.
  3. For each entry in the seed list:
       a. UPSERT a row in `securities` (ON CONFLICT on (name) via a
          synthetic unique look-up; we resolve by (symbol, exchange)).
       b. UPSERT a row in `instruments` (ON CONFLICT (symbol, exchange) DO NOTHING).
  4. After rows are inserted, fetch daily OHLCV bars from EODHD for each new
     instrument (≤5 concurrent workers to stay inside T3 rate limits).
  5. Mark has_ohlcv=true on instruments where bars were fetched.

WHY Option A over Option B (event-native):
  The event bus path requires the market-ingestion consumer to be up and the
  Kafka lag to drain — on a local dev stack that could take hours for 500+
  symbols.  A direct DB write with EODHD HTTP fetch is faster, is what the
  existing backfill_ohlcv_etfs.py script does, and is equally idempotent.

RATE-LIMIT STRATEGY (EODHD T3 tier):
  - Semaphore of 5 concurrent fetch-workers (configurable via CONCURRENCY env).
  - 0.35 s sleep after each successful fetch.
  - On 429: 10 s back-off then single retry.
  - Graceful degradation: symbols that fail OHLCV fetch are still inserted
    with has_ohlcv=false.

IDEMPOTENCY:
  - securities UPSERT uses ON CONFLICT (symbol, exchange) on a composite
    lookup: we first try to find by (symbol, exchange) in instruments; if the
    security already exists we reuse its id.
  - instruments UPSERT uses ON CONFLICT (symbol, exchange) DO NOTHING.
  - OHLCV bars use the same ON CONFLICT / priority-guard as backfill_ohlcv_etfs.

USAGE:
    # From repo root with .venv312 active:
    python -m scripts.ops.seed_universe

    # Dry-run (inserts rows, skips OHLCV fetch):
    SKIP_OHLCV=1 python -m scripts.ops.seed_universe

    # Override DB / API key:
    MARKET_DATA_DSN=postgresql://... EODHD_API_KEY=xxx python -m scripts.ops.seed_universe

ENV VARS:
    MARKET_DATA_DSN  — asyncpg DSN  (default: postgresql://postgres:postgres@localhost:5432/market_data_db)
    EODHD_API_KEY    — EODHD key    (auto-read from market-ingestion container if empty)
    EODHD_BASE_URL   — default https://eodhd.com/api
    BACKFILL_START   — ISO date     (default: 365 calendar days ago)
    BACKFILL_END     — ISO date     (default: today)
    CONCURRENCY      — fetch workers (default: 5)
    SKIP_OHLCV       — set to "1" to skip OHLCV fetch (insert metadata only)
    UNIVERSE_PATH    — path to universe.json (default: infra/seeds/universe.json relative to repo root)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import asyncpg
import httpx

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/market_data_db"
_DEFAULT_BASE_URL = "https://eodhd.com/api"
_EODHD_PROVIDER_PRIORITY = 80  # matches existing backfill_ohlcv_etfs.py convention

# ── Repo root & seed file ──────────────────────────────────────────────────────

# WHY __file__-relative: the script lives in scripts/ops/, seed in infra/seeds/.
# Using __file__ keeps it portable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_UNIVERSE_PATH = _REPO_ROOT / "infra" / "seeds" / "universe.json"


# ── EODHD fetch ───────────────────────────────────────────────────────────────


async def _fetch_eodhd_eod(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    symbol: str,
    exchange: str,
    from_date: str,
    to_date: str,
    api_key: str,
    base_url: str,
) -> list[dict[str, Any]]:
    """Fetch daily EOD bars from EODHD under a shared semaphore.

    WHY semaphore + sleep: EODHD T3 tier is documented at ~1 req/s for EOD
    bars; 5 concurrent workers with 0.35 s delay ≈ ~14 req/s burst then
    throttles naturally via the 429 back-off.
    """
    async with sem:
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
            print(f"  [WARN] {symbol}: EODHD 404 (not on exchange {exchange})")
            return []
        if resp.status_code == 429:
            print(f"  [WARN] {symbol}: rate-limited (429) — sleeping 10 s")
            await asyncio.sleep(10)
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                print(f"  [ERROR] {symbol}: retry HTTP {resp.status_code}")
                return []
        if resp.status_code != 200:
            print(f"  [ERROR] {symbol}: unexpected HTTP {resp.status_code}")
            return []

        try:
            data = resp.json()
        except Exception as exc:
            print(f"  [ERROR] {symbol}: JSON parse — {exc}", file=sys.stderr)
            return []

        if not isinstance(data, list):
            print(f"  [WARN] {symbol}: non-list payload type={type(data).__name__}")
            return []

        # Polite inter-request delay regardless of cache hit
        await asyncio.sleep(0.35)
        return data  # type: ignore[return-value]


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def _upsert_security_and_instrument(
    conn: asyncpg.Connection,
    entry: dict[str, Any],
) -> str | None:
    """Insert (securities + instruments) for one universe entry.

    Returns the instrument_id UUID string on success, None on error.

    STRATEGY:
    1. Look up existing instrument by (symbol, exchange).  If found, reuse
       its security_id — avoids orphan security rows from re-runs.
    2. If not found, insert a new security row and then a new instrument row.
    3. ON CONFLICT (symbol, exchange) DO NOTHING on instruments means
       concurrent runs are safe; we return the existing id in that case.
    """
    symbol: str = entry["symbol"]
    exchange: str = entry["exchange"]
    name: str = entry.get("name") or symbol
    sector: str | None = entry.get("sector")

    # ── Map asset_type to currency heuristic ─────────────────────────────
    # WHY: securities.currency must not be NULL for downstream display;
    # use sensible defaults per asset class.
    if exchange == "CC":
        currency = "USD"
        country = None
    elif exchange == "FOREX":
        # base currency of the pair, or USD for metals
        currency = "USD"
        country = None
    elif exchange == "INDX":
        currency = "USD"
        country = "USA"
    else:
        currency = "USD"
        country = "USA"

    try:
        # Step 1: check for existing instrument
        existing = await conn.fetchrow(
            "SELECT id, security_id FROM instruments WHERE symbol=$1 AND exchange=$2",
            symbol,
            exchange,
        )
        if existing is not None:
            # Already present — return existing instrument id (idempotent)
            return str(existing["id"])

        # Step 2: insert security row
        # WHY no UNIQUE constraint on (name): securities may share a display
        # name (e.g. "Realty Income" appears twice in S&P 500 due to REIT
        # reclassification). We use the INSERT … RETURNING id pattern and
        # accept duplicate security rows for rare duplicate names.
        security_id: str = await conn.fetchval(
            """
            INSERT INTO securities (name, sector, currency, country)
            VALUES ($1, $2, $3, $4)
            RETURNING id::text
            """,
            name,
            sector,
            currency,
            country,
        )

        # Step 3: insert instrument row
        # ON CONFLICT DO NOTHING: if a concurrent script inserted between our
        # check and this insert, we simply fetch and return the winner's id.
        instrument_id: str | None = await conn.fetchval(
            """
            INSERT INTO instruments (security_id, symbol, exchange, currency_code, sector, name)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (symbol, exchange) DO NOTHING
            RETURNING id::text
            """,
            security_id,
            symbol,
            exchange,
            currency,
            sector,
            name,
        )

        if instrument_id is None:
            # Lost the race — fetch the winner's id
            instrument_id = await conn.fetchval(
                "SELECT id::text FROM instruments WHERE symbol=$1 AND exchange=$2",
                symbol,
                exchange,
            )

        return instrument_id

    except Exception as exc:
        print(f"  [ERROR] DB upsert {symbol}/{exchange}: {exc}", file=sys.stderr)
        return None


async def _upsert_bars(
    conn: asyncpg.Connection,
    instrument_id: str,
    bars: list[dict[str, Any]],
) -> int:
    """Bulk-upsert parsed daily OHLCV rows into ohlcv_bars.

    Identical semantics to backfill_ohlcv_etfs.py — priority-guarded
    ON CONFLICT so a higher-priority provider is never overwritten.
    """
    if not bars:
        return 0

    records: list[tuple] = []
    for raw in bars:
        try:
            bar_date = datetime.strptime(raw["date"], "%Y-%m-%d").replace(tzinfo=UTC)
            open_ = Decimal(str(raw["open"]))
            high = Decimal(str(raw["high"]))
            low = Decimal(str(raw["low"]))
            close = Decimal(str(raw["close"]))
            adj = Decimal(str(raw.get("adjusted_close") or raw["close"]))
            volume = int(raw.get("volume") or 0)
        except (KeyError, ValueError, InvalidOperation) as exc:
            print(f"    [SKIP] malformed bar {raw!r}: {exc}", file=sys.stderr)
            continue

        records.append(
            (
                instrument_id,
                "1d",
                bar_date,
                open_,
                high,
                low,
                close,
                volume,
                adj,
                "eodhd",
                _EODHD_PROVIDER_PRIORITY,
                False,  # is_derived
                False,  # is_partial
            )
        )

    if not records:
        return 0

    sql = """
        INSERT INTO ohlcv_bars
            (instrument_id, timeframe, bar_date,
             open, high, low, close, volume, adjusted_close,
             source, provider_priority, is_derived, is_partial)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        ON CONFLICT (instrument_id, timeframe, bar_date)
        DO UPDATE SET
            open              = EXCLUDED.open,
            high              = EXCLUDED.high,
            low               = EXCLUDED.low,
            close             = EXCLUDED.close,
            volume            = EXCLUDED.volume,
            adjusted_close    = EXCLUDED.adjusted_close,
            source            = EXCLUDED.source,
            provider_priority = EXCLUDED.provider_priority,
            is_partial        = EXCLUDED.is_partial
        WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority
    """
    await conn.executemany(sql, records)
    return len(records)


async def _mark_has_ohlcv(conn: asyncpg.Connection, instrument_id: str) -> None:
    """Set has_ohlcv=true on the instrument once bars are confirmed present."""
    await conn.execute(
        "UPDATE instruments SET has_ohlcv=true WHERE id=$1",
        instrument_id,
    )


# ── OHLCV worker ──────────────────────────────────────────────────────────────


async def _ohlcv_worker(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    conn: asyncpg.Connection,
    symbol: str,
    exchange: str,
    instrument_id: str,
    from_date: str,
    to_date: str,
    api_key: str,
    base_url: str,
) -> int:
    """Fetch + upsert bars for a single instrument. Returns bar count."""
    raw_bars = await _fetch_eodhd_eod(sem, client, symbol, exchange, from_date, to_date, api_key, base_url)
    if not raw_bars:
        return 0
    count = await _upsert_bars(conn, instrument_id, raw_bars)
    if count > 0:
        await _mark_has_ohlcv(conn, instrument_id)
    return count


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    # ── Config ─────────────────────────────────────────────────────────────
    dsn = os.environ.get("MARKET_DATA_DSN", _DEFAULT_DSN)
    base_url = os.environ.get("EODHD_BASE_URL", _DEFAULT_BASE_URL)
    skip_ohlcv = os.environ.get("SKIP_OHLCV", "0") == "1"
    concurrency = int(os.environ.get("CONCURRENCY", "5"))

    universe_path = Path(os.environ.get("UNIVERSE_PATH", str(_DEFAULT_UNIVERSE_PATH)))
    if not universe_path.exists():
        print(f"[ERROR] Universe file not found: {universe_path}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("EODHD_API_KEY", "")
    if not api_key and not skip_ohlcv:
        # Try to auto-discover from the running container (dev shortcut)
        try:
            result = subprocess.run(
                ["docker", "exec", "worldview-market-ingestion-1", "printenv", "MARKET_INGESTION_EODHD_API_KEY"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            api_key = result.stdout.strip()
        except Exception as exc:
            print(f"[DEBUG] container key lookup failed: {exc}")

    if not api_key and not skip_ohlcv:
        print("[ERROR] EODHD_API_KEY required (or set SKIP_OHLCV=1)", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    from_date = os.environ.get("BACKFILL_START", (today - timedelta(days=365)).isoformat())
    to_date = os.environ.get("BACKFILL_END", today.isoformat())

    # ── Load universe ───────────────────────────────────────────────────────
    with open(universe_path, encoding="utf-8") as fp:
        universe_data = json.load(fp)

    entries: list[dict[str, Any]] = universe_data["instruments"]

    # Deduplicate within the JSON (some symbols like 'O', 'ADSK' appear twice)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for e in entries:
        key = (e["symbol"], e["exchange"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    entries = deduped

    print(f"[INFO] Universe: {len(entries)} unique (symbol, exchange) pairs")
    print(f"[INFO] OHLCV range: {from_date} → {to_date} | skip_ohlcv={skip_ohlcv} | concurrency={concurrency}")
    print(f"[INFO] DB: {dsn.split('@')[-1]}")

    # ── Connect ─────────────────────────────────────────────────────────────
    conn: asyncpg.Connection = await asyncpg.connect(dsn)

    # Pre-flight: count existing instruments so we can report delta
    existing_count_before: int = await conn.fetchval("SELECT count(*) FROM instruments")
    print(f"[INFO] instruments before: {existing_count_before}")

    # ── Phase 1: upsert all securities + instruments ─────────────────────────
    print("\n[PHASE 1] Inserting securities + instruments …")
    instrument_map: dict[tuple[str, str], str] = {}  # (symbol, exchange) → instrument_id
    errors = 0

    for i, entry in enumerate(entries):
        sym = entry["symbol"]
        exch = entry["exchange"]
        instrument_id = await _upsert_security_and_instrument(conn, entry)
        if instrument_id is None:
            errors += 1
        else:
            instrument_map[(sym, exch)] = instrument_id

        if (i + 1) % 50 == 0 or (i + 1) == len(entries):
            print(f"  processed {i + 1}/{len(entries)} …")

    existing_count_after: int = await conn.fetchval("SELECT count(*) FROM instruments")
    new_rows = existing_count_after - existing_count_before
    print(f"\n[PHASE 1 DONE] instruments after: {existing_count_after} (+{new_rows} new | {errors} errors)")

    # ── Phase 2: OHLCV backfill ──────────────────────────────────────────────
    total_bars = 0
    ohlcv_errors: list[str] = []

    if skip_ohlcv:
        print("\n[PHASE 2] SKIP_OHLCV=1 — skipping OHLCV fetch")
    else:
        print(f"\n[PHASE 2] Fetching OHLCV bars for {len(instrument_map)} instruments (concurrency={concurrency}) …")

        sem = asyncio.Semaphore(concurrency)
        items = list(instrument_map.items())

        # WHY gather inside the async-with block:
        # We must keep the httpx.AsyncClient open until ALL coroutines finish.
        # Using asyncio.create_task + as_completed can let the context manager
        # close the client before queued tasks get a semaphore slot — causing
        # "Cannot send a request, as the client has been closed." errors.
        # asyncio.gather waits for every coroutine before the context exits.
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:

            async def _worker_with_progress(
                sym: str,
                exch: str,
                inst_id: str,
                idx: int,
                total: int,
            ) -> int:
                count = await _ohlcv_worker(
                    sem,
                    http,
                    conn,
                    sym,
                    exch,
                    inst_id,
                    from_date,
                    to_date,
                    api_key,
                    base_url,
                )
                done = idx + 1
                if done % 50 == 0 or done == total:
                    print(f"  OHLCV progress: {done}/{total} symbols done …")
                return count

            results = await asyncio.gather(
                *[
                    _worker_with_progress(sym, exch, inst_id, i, len(items))
                    for i, ((sym, exch), inst_id) in enumerate(items)
                ],
                return_exceptions=True,
            )

        # Tally totals (exceptions count as 0 bars, not a fatal error)
        completed = 0
        for r in results:
            if isinstance(r, int):
                total_bars += r
                completed += 1
            else:
                print(f"  [WARN] worker raised: {r}", file=sys.stderr)
        print(f"  OHLCV done: {completed}/{len(items)} workers succeeded, {total_bars} bars total")

        # Tally OHLCV errors (symbols with 0 bars that were expected to have data)
        no_ohlcv = await conn.fetch(
            """
            SELECT i.symbol, i.exchange
            FROM instruments i
            WHERE i.id = ANY($1::uuid[])
              AND i.has_ohlcv = false
            """,
            list(instrument_map.values()),
        )
        ohlcv_errors = [f"{r['symbol']}.{r['exchange']}" for r in no_ohlcv]

    # ── Final summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[SUMMARY]")
    final_count: int = await conn.fetchval("SELECT count(*) FROM instruments")
    has_ohlcv: int = await conn.fetchval("SELECT count(*) FROM instruments WHERE has_ohlcv")
    has_fundamentals: int = await conn.fetchval("SELECT count(*) FROM instruments WHERE has_fundamentals")

    print(f"  Total instruments  : {final_count}")
    print(f"  New rows inserted  : {new_rows}")
    print(f"  DB errors          : {errors}")
    print(f"  has_ohlcv=true     : {has_ohlcv}")
    print(f"  has_fundamentals   : {has_fundamentals}")
    if not skip_ohlcv:
        print(f"  Total bars upserted: {total_bars}")
        if ohlcv_errors:
            print(f"  Symbols with 0 bars ({len(ohlcv_errors)}): {', '.join(ohlcv_errors[:30])}")
            if len(ohlcv_errors) > 30:
                print(f"    … and {len(ohlcv_errors) - 30} more")

    target_met = final_count >= 600
    print(f"\n  Target ≥600: {'PASS' if target_met else 'FAIL'} ({final_count})")

    await conn.close()

    if errors and final_count < 600:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
