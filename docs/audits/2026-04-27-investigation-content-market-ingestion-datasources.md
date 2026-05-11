# Investigation Report: Content-Ingestion & Market-Ingestion Data Source Validation

**Date**: 2026-04-27  
**Investigator**: Claude (investigation skill)  
**Severity**: HIGH (multiple sources producing 0 data; crypto OHLCV all failing)  
**Status**: Root causes identified and fixed (4 bugs)

---

## 1. Issue Summary

The user requested validation that all data sources in `market-ingestion` (S2) and `content-ingestion` (S4) are correctly ingesting data, given that API keys are already configured. Investigation revealed 4 distinct bugs causing significant ingestion failures, plus 1 configuration issue (EODHD demo key) requiring user action.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| 276 failed market-ingestion tasks | `ingestion_db.ingestion_tasks` | All EODHD tasks fail with HTTP 403 |
| 22 Alpaca HTTP 400 failures | `ingestion_db.ingestion_tasks` | Crypto + class shares rejected by stock endpoint |
| `scheduler_unsupported_dataset_type dataset_type=yield_curve` | Scheduler container logs | Pre-f1ad800 image deployed despite new code |
| `"Can't reconnect until invalid transaction is rolled back"` | Content-ingestion worker logs | Session poisoning leaving tasks stuck in CLAIMED |
| `{"message":"invalid symbol: BRK-B"}` | Alpaca API direct test | Class share dash format rejected |
| `worldview-market-ingestion-scheduler:latest` (1.33GB) vs `worldview-market-ingestion:latest` (614MB) | `docker images` | Separate images per role — base rebuild doesn't update scheduler/worker |
| `MARKET_INGESTION_EODHD_API_KEY=demo` | `configs/docker.env` | Demo key causes HTTP 403 on all real endpoints |

---

## 3. Root Causes & Fixes Applied

### Issue 1: Market-Ingestion Scheduler Using Pre-f1ad800 Image (Fixed)

**Root cause**: `docker compose build market-ingestion` only rebuilds the base service image (`worldview-market-ingestion:latest`). The scheduler and worker each have separate `build:` blocks producing their own image tags (`worldview-market-ingestion-scheduler`, `worldview-market-ingestion-worker`). These were not rebuilt, so the containers still ran the old code without `YIELD_CURVE`/`MARKET_CAP` handlers in `_build_incremental_task()`.

**Symptom**: Scheduler logs showed `scheduler_unsupported_dataset_type dataset_type=yield_curve` for 7+ symbols. 0 yield_curve/market_cap tasks generated.

**Fix**: Rebuilt all three images with `--no-cache` (required to bypass BuildKit layer cache):
```bash
docker compose build --no-cache market-ingestion market-ingestion-scheduler market-ingestion-worker
docker compose up -d --force-recreate market-ingestion-scheduler market-ingestion-worker
```

**New pattern**: BP-245

---

### Issue 2: Alpaca Adapter Sends Crypto Symbols to Stock Endpoint (Fixed)

**Root cause**: `AlpacaProviderAdapter.fetch_ohlcv()` always used `/v2/stocks/bars`. Alpaca's stock endpoint rejects crypto symbols (`BTC-USD`, `ETH-USD`, etc.) with HTTP 400. Crypto requires `/v1beta3/crypto/us/bars` with `BTC/USD` slash format (no `feed` parameter).

**Affected symbols**: `BTC-USD`, `ETH-USD`, `BNB-USD`, `ADA-USD`, `XRP-USD`, `DOGE-USD`, `SOL-USD`, `LTC-USD`, `AVAX-USD`, `MATIC-USD` (10 crypto symbols, 22 total failures with duplicates)

**Fix**:
- Added `_is_crypto_symbol()` — detects `-USD` suffix
- Added `_to_alpaca_crypto_symbol()` — converts `BTC-USD` → `BTC/USD`  
- `fetch_ohlcv()` and `fetch_ohlcv_batch()` now route crypto to `/v1beta3/crypto/us/bars`

**Result**: 21/22 tasks succeeded immediately after reset; 1 had a timeout that auto-retried.

**New pattern**: BP-243

---

### Issue 3: Alpaca Rejects Class Share Dash Format (Fixed)

**Root cause**: Alpaca requires dot notation for class shares (`BRK.B`), but our house format uses dashes (`BRK-B`). Alpaca returns `{"message":"invalid symbol: BRK-B"}` HTTP 400.

**Fix**: Added `_to_alpaca_equity_symbol()` that converts `-` → `.` for non-crypto equity symbols.

**New pattern**: BP-244

---

### Issue 4: SQLAlchemy Session Poisoning Leaves Tasks Stuck in CLAIMED (Fixed)

**Root cause**: When a DB connection drops mid-transaction, the outer session becomes "poisoned". The exception handler's `session.rollback()` also fails. The subsequent `task_repo.update_status(RETRY)` via the same session also fails. Tasks remain stuck in `CLAIMED` status, only recoverable via `recover_expired_leases()` lease timeout (adds delay).

**Fix**: Added `_rescue_stuck_task()` method in `content_ingestion/infrastructure/workers/worker.py` that:
1. Opens a fresh session via `_write_factory()`
2. Writes the terminal status via a clean connection
3. Exception handler now swallows rollback errors and always calls rescue

**New pattern**: BP-246

---

### Issue 5: EODHD Demo API Key (Requires User Action)

**Root cause**: `MARKET_INGESTION_EODHD_API_KEY=demo` in `configs/docker.env`. The demo key causes HTTP 403 on all real EODHD endpoints (real-time quotes, EOD OHLCV, fundamentals, economic events, macro indicators, insider transactions, earnings calendar, news sentiment).

**Affected**: 254 market-ingestion tasks permanently failed:
- quotes: 116 (EODHD real-time)
- ohlcv: 62 (EODHD EOD)
- fundamentals: 58
- economic_events: 6
- macro_indicator: 5
- insider_transactions: 3
- news_sentiment: 2
- earnings_calendar: 2

**Working without EODHD**: Alpaca (OHLCV intraday), Polygon (OHLCV fallback), Yahoo Finance (EOD OHLCV for non-EODHD symbols).

**Action required**: Set `MARKET_INGESTION_EODHD_API_KEY=<real_key>` in `configs/docker.env`, then reset failed EODHD tasks:
```sql
UPDATE ingestion_tasks
SET status='pending', last_error=NULL, attempt=0, locked_by=NULL, locked_until=NULL, updated_at=NOW()
WHERE status='failed' AND last_error LIKE '%EODHD%';
```

---

## 4. Final State After Fixes

### Market-Ingestion (`ingestion_db.ingestion_tasks`)

| Status | dataset_type | Count | Notes |
|--------|-------------|-------|-------|
| succeeded | ohlcv | 413 | Alpaca (crypto + equity) + Yahoo Finance |
| succeeded | fundamentals | 8 | EODHD (demo-accessible endpoints) |
| succeeded | news_sentiment | 6 | EODHD demo-accessible |
| succeeded | quotes | 16 | EODHD demo-accessible |
| failed | quotes | 116 | EODHD real-time (demo key) |
| failed | ohlcv | 62 | EODHD EOD (demo key) |
| failed | fundamentals | 58 | EODHD (demo key) |
| failed | economic_events | 6 | EODHD (demo key) |
| failed | macro_indicator | 5 | EODHD (demo key) |
| failed | insider_transactions | 3 | EODHD (demo key) |
| failed | earnings_calendar | 2 | EODHD (demo key) |
| failed | news_sentiment | 2 | EODHD (demo key) |

### Content-Ingestion (`content_ingestion_db.content_ingestion_tasks`)

| Status | source_type | Count | Notes |
|--------|-------------|-------|-------|
| succeeded | finnhub | 2331 | Fully operational |
| succeeded | newsapi | 551 | Fully operational |
| succeeded | polymarket | 307 | Fully operational |
| failed | eodhd | 11 | Intentionally disabled (demo key) |
| pending | finnhub | 7 | Queued |
| retry | finnhub | 2 | Will retry |

---

## 5. Recommendations

1. **Provide real EODHD API key**: This unlocks quotes, fundamentals, economic events, macro indicators, insider transactions, earnings calendar — the core financial data foundation.

2. **Add crypto test fixtures**: The Alpaca adapter test only tested equity symbols. Add `BTC-USD` and `BRK-B` to the test suite to catch routing issues at test time (not production).

3. **Consolidate per-role Docker images**: Consider using a single image with a CMD/ENTRYPOINT arg for different roles, rather than separate `build:` blocks. This eliminates the "rebuilt but deployed old code" class of bugs.

4. **Add session rescue to market-ingestion**: The same SQLAlchemy session poisoning pattern can affect market-ingestion workers. Apply the same `_rescue_stuck_task()` pattern there.
