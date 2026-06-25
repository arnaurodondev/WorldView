# Data Gaps Investigation — 2026-06-07

**Investigator**: Claude (automated)
**Platform state**: All containers healthy, ingestion pipeline active, Kafka connected

---

## Summary

Five QA gaps investigated. Two are code bugs (Gap 3, Gap 4), two are data gaps / config issues (Gap 2, Gap 5), and one is a mix of design-correct behaviour and a residual seed artifact (Gap 1). No code changes were made.

---

### Gap 1: OHLCV data quality

**Root cause**: Three distinct issues, none requiring a code fix:

1. **`source=derived` bars (13/58)**: These are correct by design. The `IntradayResamplingWorker` resamples 1m intraday Alpaca/EODHD bars to daily via `ResampledOHLCVUseCase`. All 13 derived `1d` bars have `is_partial=True` — they represent the current trading day's rolling aggregate and are correctly labelled. They are not phantom bars; they reflect real intraday activity.

2. **Low-volume bars (volume < 1000)**: All low-volume bars are derived partial-day bars (e.g. `2026-05-12: volume=434`, `2026-05-21: volume=1443`, `2026-05-29: volume=199`). Their low volume is expected — a partial-day resample captures only bars that had arrived by the last ingest trigger (typically early in the trading session). Not a pipeline artifact; EODHD daily bars for the same dates show 15–50M volume.

3. **`source=seed_demo` bar (2026-04-03)**: One seed_demo bar survives the `period=1y` filter because it falls within the 1-year window. The DB contains 4 seed_demo bars total (2026-01-01, 2026-01-19, 2026-02-16, 2026-04-03) — the earlier three are filtered by the `period=1y` range start (`2026-03-09`). The 2026-04-03 bar has `adjusted_close=null` (no adjustment applied) and sits in the middle of real EODHD bars. This creates a visible price discontinuity in charts (AAPL seed bar shows ~$192 between real $255+ bars).

**Evidence**:
- All 13 derived bars confirmed `is_partial=True` in `ohlcv_bars` table
- DB query: `SELECT bar_date, volume, is_partial FROM ohlcv_bars WHERE source='derived' AND timeframe='1d'` — all have `is_partial=t`
- Seed bar: `SELECT bar_date, close, source FROM ohlcv_bars WHERE source='seed_demo' AND instrument_id='01900000-...-001001'` → 4 rows, 1 within 1y window

**Severity**: EXPECTED (derived + partial bars), DATA_GAP (seed_demo survivor in live window)

**Fix**: The seed_demo bar at 2026-04-03 can be deleted directly from the DB: `DELETE FROM ohlcv_bars WHERE source='seed_demo' AND bar_date > '2026-03-01'`. No code change needed. The derived/partial bars are correct by design.

---

### Gap 2: Stale prices (`prices_stale: true`, `prices_as_of: null`)

**Root cause**: NFLX (`instrument_id=01900000-0000-7000-8000-000000001009`) has no row in the `quotes` table and no `quotes` polling policy in `ingestion_db`. The `holdings` table contains 10 instruments including NFLX; `GetExposureUseCase` calls `HttpCurrentPriceClient.get_current_prices()` which calls `POST /api/v1/quotes/batch`. The batch endpoint returns `{"01900000-...-001009": null}` for NFLX. The client code (line 163 in `current_price_client.py`) skips entries where `isinstance(quote, dict)` is False — so NFLX yields no price. The use case then falls back to `average_cost` for NFLX and sets `prices_stale=True` for the entire portfolio response.

`prices_as_of=None` is intentional by design — the docstring in `ExposureResult` explicitly documents it as a v1 limitation ("the port doesn't yet surface a per-quote timestamp").

**Evidence**:
- `SELECT COUNT(*) FROM quotes WHERE instrument_id='01900000-...-001009'` → `0`
- `SELECT dataset_type FROM polling_policies WHERE symbol='NFLX'` → no `quotes` entry
- `POST /api/v1/quotes/batch` with NFLX ID → `{"01900000-...-001009": null}`
- Other 9 instruments: quotes exist and return valid `last` prices

**Severity**: CONFIG (missing quotes polling policy for NFLX seed instrument)

**Fix**: Add a `quotes` polling policy for NFLX in `ingestion_db.polling_policies`. Alternatively, run a manual ingest trigger: `POST /api/v1/ingest/trigger` with `{symbol: "NFLX", dataset_type: "quotes"}`. The staleness flag clears once any quote is ingested. Note: AAPL has a `quotes` policy but it is `enabled=false` — so AAPL quotes are also at risk of becoming stale after the last successful run (2026-06-03).

---

### Gap 3: Holdings sector = "Unknown"

**Root cause**: Code bug in `api-gateway/src/api_gateway/routes/portfolio.py` (`get_portfolio_sector_attribution`, line 851–862). The sector attribution handler calls `GET /api/v1/fundamentals/{instrument_id}?sections=General` on S3 market-data. However, S3's `GET /fundamentals/{instrument_id}` endpoint does **not** accept a `sections` query parameter — it ignores it and returns ALL sections as a flat list of `records` (each with a `section` field). The gateway then attempts `data.get("General", {}).get("Sector")` on the raw response, which has no top-level `"General"` key. The sector always resolves to `"Unknown"`.

The sector data **does exist** in the DB — confirmed: AAPL has `data->>'Sector'='Technology'`, `data->>'GicSector'='Information Technology'` in `company_profiles`. The correct S3 endpoint to call is `GET /api/v1/fundamentals/{instrument_id}/company-profile`, which returns `records[0].data.Sector` directly.

**Evidence**:
- `GET /api/v1/fundamentals/01900000-...-001001?sections=General` returns all 17 sections (ignores the param)
- `GET /api/v1/fundamentals/01900000-...-001001/company-profile` returns `{"Sector": "Technology", "GicSector": "Information Technology"}`
- `SELECT data->>'Sector' FROM company_profiles WHERE instrument_id='01900000-...-001001'` → `Technology`
- Live endpoint: `GET /v1/portfolios/{id}/sector-attribution` → all 9 holdings bucketed as `"Unknown"`, `covered_pct=0.0`

**Severity**: BUG

**Fix**: In `routes/portfolio.py::_fetch_sector()`, replace the generic fundamentals call with the specific company-profile endpoint:
```python
# WRONG: ignores sections param, no General key in response
r = await clients.market_data.get(
    f"/api/v1/fundamentals/{iid}",
    params={"sections": "General"},
    headers=s3_headers,
)
sector = str(data.get("General", {}).get("Sector") or "Unknown")

# CORRECT:
r = await clients.market_data.get(
    f"/api/v1/fundamentals/{iid}/company-profile",
    headers=s3_headers,
)
if r.status_code == 200:
    data = r.json()
    records = data.get("records", [])
    sector = str(records[0].get("data", {}).get("Sector") or "Unknown") if records else "Unknown"
```

---

### Gap 4: Lots empty for all holdings

**Root cause**: Holdings and transactions in `portfolio_db` use **different instrument ID namespaces**. The `holdings` table contains seed instrument IDs (`01900000-0000-7000-8000-000000001001` through `..001010`), while the `transactions` table contains real UUIDv7 instrument IDs ingested via the brokerage sync (e.g. `019e0dbf-830c-793b-be2b-ed702f1c589b`). The `GetHoldingLotsUseCase` walks transactions for the given `portfolio_id` looking for rows with `instrument_id = <requested_seed_id>` — but no transaction rows match those seed IDs. FIFO deque stays empty, lots array is always `[]`.

This is a seed data inconsistency: `make seed` inserted seed holdings with synthetic IDs, but transactions were written by brokerage sync using real market-data instrument IDs. The two sets have no overlap.

**Evidence**:
- `SELECT instrument_id FROM holdings WHERE portfolio_id='01900000-...-000100'` → 10 rows with IDs `01900000-...-00100{1..10}`
- `SELECT DISTINCT instrument_id FROM transactions WHERE portfolio_id='01900000-...-000100'` → IDs like `019e0dbf-...`, `019e0db5-...` (none matching seed IDs)
- `GET /v1/portfolios/{id}/holdings/{instrument_id}/lots` → `{"lots": [], "total_qty": "0.00", "total_cost": "0.00"}`
- Total transactions in portfolio: 275 rows — all with non-seed instrument IDs

**Severity**: DATA_GAP (seed data inconsistency — not a code bug; the code is correct)

**Fix**: Not fixable without data re-seeding. Options:
1. Re-run `make seed` ensuring that transactions are generated using the same seed instrument IDs as the holdings (`01900000-...`) rather than live-ingested IDs.
2. Alternatively, backfill synthetic BUY transactions for each holding using the seed instrument IDs and the `average_cost` and `quantity` columns from the holdings table.

---

### Gap 5: Provider data verification

**Root cause**: Multiple observations, all expected or explained:

1. **Scheduler enqueuing 0 tasks**: Normal. All `ingestion_tasks` have status `succeeded` or `failed` — no tasks are PENDING or RUNNING. The scheduler's `scheduler_skip_active_task` log lines indicate tasks are skipped because they already have a recent completion (watermark check). Tasks will re-appear when their `base_interval_sec` elapses. EODHD ingestion pipeline is active and healthy.

2. **Worker claiming 0 tasks**: Normal — follows directly from point 1. No tasks in PENDING state.

3. **OHLCV consumer periodic Kafka reconnects**: The consumer logs show `kafka_connectivity_probe_failed → exiting_with_code_2_for_dns_refresh` roughly every 10 hours. This is the library's built-in DNS refresh mechanism (not an error): after 5 minutes of Kafka transport failures, the consumer process exits with code 2 and is restarted by Docker to get a fresh DNS lookup. The consumer restarts successfully each time and shows `kafka_consumer_started`. This is cosmetic in dev; in production a proper Kafka broker hostname (not DNS-volatile) would eliminate these restarts.

4. **EODHD ingestion active**: Confirmed. `ingestion_tasks` shows recent `succeeded` timestamps for AAPL, NFLX, GOOGL, etc. for `ohlcv`, `fundamentals`, `insider_transactions`, and `market_cap` dataset types. Last AAPL OHLCV success: `2026-06-07 16:01:06`. Fundamentals ingested: `2026-06-07 03:31:58` (AAPL `last_fundamentals_ingest_at`).

5. **Intraday resampling consumer**: Same Kafka reconnect pattern as the OHLCV consumer. Restarts cleanly. The derived bars being produced indicate the resampling pipeline was operational before the last reconnect cycle.

**Evidence**:
- `docker logs worldview-market-ingestion-scheduler-1` → `tasks_enqueued=0 budget_limited=0`
- `docker logs worldview-market-ingestion-worker-1` → `claimed=0 requested=10` (no pending tasks)
- `SELECT status, COUNT(*) FROM ingestion_tasks GROUP BY status` → `succeeded: 11488, failed: 140`
- `SELECT completed_at FROM ingestion_tasks WHERE symbol='NFLX' AND dataset_type='ohlcv' ORDER BY completed_at DESC LIMIT 1` → `2026-06-07 16:01:06`

**Severity**: EXPECTED (scheduler idle + consumer reconnects are normal behaviour)

**Fix**: No action required for Gap 5. The periodic Kafka reconnects can be mitigated long-term by tuning `KAFKA_BROKER` to a stable hostname or increasing `kafka_connectivity_probe_failed` threshold, but this is a dev-environment concern, not a data pipeline bug.

---

## Actionable Code Bugs

| # | Gap | File | Severity | Description |
|---|-----|------|----------|-------------|
| 1 | Gap 3 | `services/api-gateway/src/api_gateway/routes/portfolio.py` L851–862 | BUG | `_fetch_sector()` calls wrong fundamentals endpoint — uses generic `GET /fundamentals/{id}?sections=General` which ignores the `sections` param and returns no `General` key. Should call `GET /fundamentals/{id}/company-profile` and read `records[0].data.Sector`. Affects all 10 holdings → all show "Unknown" sector. |

## Data Gaps (non-code, require re-seeding or config)

| # | Gap | Severity | Description |
|---|-----|----------|-------------|
| 2 | Gap 2 | CONFIG | NFLX missing quotes polling policy → no row in `quotes` table → `prices_stale=True` on portfolio exposure |
| 3 | Gap 1 | DATA_GAP | One `source=seed_demo` bar (2026-04-03) falls within the 1y OHLCV window, creating a visible price discontinuity at ~$192 amid real $255+ bars |
| 4 | Gap 4 | DATA_GAP | Holdings use seed instrument IDs; transactions use brokerage-sync UUIDv7 IDs — no overlap → FIFO lot walk always returns empty |

## Items Confirmed as Expected Behaviour

- `source=derived` + `is_partial=True` bars: correct intraday resampling output
- `prices_as_of=null`: documented v1 limitation in use case docstring
- Scheduler/worker 0 tasks: all tasks completed, watermark intervals not yet elapsed
- Kafka DNS-refresh restarts: library-level reconnect mechanism, not a data loss event
