# Weekly (1w) / Monthly (1M) OHLCV Bar Temporality Gap — Root-Cause Investigation

**Date:** 2026-06-15
**Type:** READ-ONLY investigation (no code changes, no DB mutations, no restarts)
**Symptom:** Quote-tab chart had to drop the 5Y timeframe because S3 stores zero weekly bars and S9 exposes no resampling, so a 5Y view was empty.

---

## TL;DR

The platform **does** have bar-aggregation logic — two separate, well-formed use cases in S3
(`DeriveOHLCVUseCase` + `GetOrDeriveOHLCVBarsUseCase`) that aggregate stored daily bars into
weekly/monthly bars on demand. **But that logic is wired to NOTHING** — no router, no consumer,
no worker calls it. The endpoint the chart actually uses (`GET /api/v1/ohlcv/bars`,
`GetOHLCVBarsFlexibleUseCase`) does a plain table read for `1w`/`1M` and returns empty because the
`ohlcv_bars` table genuinely holds **zero weekly and zero monthly rows**.

Separately, the S2 ingestion side *does* schedule weekly/monthly polls, but they return **empty
payloads** (Yahoo windows too narrow + EODHD demo doesn't serve them), and even the rare non-empty
`1mo` payload would be **silently mislabeled as `1d`** by an enum-coercion bug in the S3 consumer.

**Category: built-but-not-run + built-but-not-exposed.** The cleanest aggregation path exists in
code but is dead. The clean fix is to wire the existing derive use case into the bars endpoint
(P0), independent of the broken ingestion path.

---

## 1. Does resampling / aggregation logic exist?

### EXISTS — daily → weekly/monthly aggregation (the right logic, unwired)

- **`services/market-data/src/market_data/application/use_cases/derive_ohlcv.py`** —
  `DeriveOHLCVUseCase`. Aggregates stored `1d` bars into `1w` (ISO-week, Monday anchor) or `1M`
  (calendar-month, day-1 anchor). open=first, high=max, low=min, close=last, volume=sum. Writes
  `is_derived=True` via `bulk_upsert_derived`. `_DERIVABLE = {ONE_WEEK, ONE_MONTH}` (`derive_ohlcv.py:50`).
- **`services/market-data/src/market_data/application/use_cases/get_or_derive_ohlcv.py`** —
  `GetOrDeriveOHLCVBarsUseCase`. On-demand cache-or-derive: for `1w`/`1M`, returns stored derived
  bars if `>= limit` exist, else runs `DeriveOHLCVUseCase` and re-fetches (`get_or_derive_ohlcv.py:95-116`).
  Pass-through for all other timeframes.
- Both originate from **PLAN-0036 W2-4 / W2-5** (cited in the module docstrings) — explicitly built
  to "eliminate EODHD API credit consumption for the 1W and 1M timeframes" by deriving locally.
- Repo support exists: `ohlcv_read.find_derived(...)` (`application/ports/repositories.py:328`,
  comment: "Used by `GetOrDeriveOHLCVBarsUseCase` to serve pre-computed weekly / monthly bars").
- Migration `007_add_ohlcv_is_derived.py` adds the `is_derived` column for the derived-bar cache.

### EXISTS — intraday resampling (different scope, does NOT cover weekly/monthly)

- **`services/market-data/src/market_data/application/use_cases/resample_ohlcv.py`** —
  `ResampledOHLCVUseCase`, driven by `IntradayResamplingWorker` (consumer group
  `market-data-intraday-resampling`). Derives `5m/15m/30m/1h/4h/1d` from `1m`.
  `_PERIOD_SECONDS` tops out at `ONE_DAY=86400` (`resample_ohlcv.py:_PERIOD_SECONDS`).
  **Weekly/monthly are deliberately absent** from this path (epoch-floor math doesn't fit
  calendar weeks/months). This is the only aggregation that is actually *running*, and it stops
  at daily. (Confirmed by DB: 5m/15m/30m/1h/4h are all 100% `is_derived`.)

### EXISTS — provider-side weekly/monthly fetch (returns empty in practice)

- `YahooFinanceProviderAdapter` supports `1w`/`1mo`/`1M`
  (`market-ingestion/.../providers/yahoo.py:_SUPPORTED_TIMEFRAMES`, `_YF_INTERVAL_MAP`).
- S2 routing prefers Yahoo for `1d|1w|1mo|1M`
  (`strategies/routing.py:24,42-66`), falling back to EODHD on zero-bar failover.
- Polling policies seed `1w` + `1mo` OHLCV policies
  (`market-ingestion/alembic/versions/0002_initial_seeds.py:191,263`).

### ABSENT

- **No router wires `GetOrDeriveOHLCVBarsUseCase` or `DeriveOHLCVUseCase`.** Grep across
  `services/market-data/src` finds the only references inside their own modules + a repo-port
  comment + a migration comment. No `api/dependencies.py` factory, no router import, no worker,
  no consumer call. The derive logic is **dead code from the live request path's perspective.**
- **No scheduled rollup worker** that periodically materializes `1w`/`1M` derived bars (unlike the
  intraday worker). PLAN-0036's intended cache-population path was never scheduled.
- **No TimescaleDB continuous aggregate / materialized view** for weekly/monthly (no
  `CREATE MATERIALIZED VIEW ... timescaledb.continuous` in any `market-data/alembic` migration).
- The flexible bars endpoint does **no** server-side resampling despite its docstring
  (see §4).

---

## 2. What intervals does storage actually hold?

`market_data_db.ohlcv_bars`, platform-wide (read-only `psql` on `worldview-postgres-1`):

| timeframe | rows    | min date   | max date   | is_derived |
|-----------|---------|------------|------------|------------|
| 1m        | 313,940 | 2026-05-09 | 2026-06-12 | 0          |
| 5m        | 52,655  | 2026-05-10 | 2026-06-12 | 52,655     |
| 15m       | 19,955  | 2026-05-10 | 2026-06-12 | 19,955     |
| 30m       | 10,885  | 2026-05-10 | 2026-06-12 | 10,885     |
| 1h        | 6,759   | 2026-05-10 | 2026-06-12 | 6,759      |
| 4h        | 3,139   | 2026-05-10 | 2026-06-12 | 3,139      |
| 1d        | 165,608 | 2025-05-10 | 2026-06-12 | 1,285      |

`SELECT DISTINCT timeframe FROM ohlcv_bars;` → **`{1m,5m,15m,30m,1h,4h,1d}` only.**
**Zero `1w`. Zero `1M`/`1mo`.** Confirmed absent.

Liquid symbol NVDA (instrument_id `01900000-0000-7000-8000-000000001006`):

| symbol | timeframe | rows | min        | max        |
|--------|-----------|------|------------|------------|
| NVDA   | 1d        | 274  | 2025-05-12 | 2026-06-12 |
| NVDA   | 1h        | 46   | 2026-05-11 | 2026-06-12 |
| NVDA   | 1m        | 1126 | 2026-05-11 | 2026-06-12 |
| NVDA   | 4h        | 19   | 2026-05-11 | 2026-06-12 |
| NVDA   | 5m/15m/30m| …    | 2026-05-11 | 2026-06-12 |
| NVDA   | **1w**    | **0**| —          | —          |
| NVDA   | **1M**    | **0**| —          | —          |

NVDA has 274 daily bars (>1 year back to 2025-05-12) — **enough source data to derive ~52 weekly +
~13 monthly bars instantly** if the derive use case were wired. The source is present; the
derived layer is empty.

---

## 3. Source provides vs. derived — intended design

PLAN-0036 (cited in `derive_ohlcv.py` docstring) established the intent explicitly: **weekly/monthly
are meant to be DERIVED LOCALLY from stored daily bars**, *not* polled from a provider, "to
eliminate EODHD API credit consumption for the 1W and 1M timeframes." So the canonical design is
local aggregation.

However, the S2 ingestion config (PLAN-0038/0040) *also* seeds `1w`/`1mo` polling policies routed
to Yahoo. This is a **conflicting/overlapping design** — and the polling path is the one that runs,
yet it produces nothing usable:

`ingestion_db.ingestion_tasks` (OHLCV, succeeded), grouped by timeframe / provider / result SHA:

| timeframe | provider       | result_ref_sha256 (prefix) | count |
|-----------|----------------|----------------------------|-------|
| 1d        | yahoo_finance  | `e3b0c442…` (EMPTY)        | 5,233 |
| 1d        | eodhd          | `e3b0c442…` (EMPTY)        | 331   |
| 1mo       | eodhd          | `e3b0c442…` (EMPTY)        | 3,364 |
| 1mo       | eodhd          | (distinct real hashes)     | ~10 (1 each) |
| 1w        | yahoo_finance  | `e3b0c442…` (EMPTY)        | 3,579 |

`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` is the **SHA-256 of empty input**
(`echo -n "" | sha256sum`). So:

- **`1w` (3,579 tasks): 100% empty payloads from Yahoo.** Tasks marked `succeeded`, `bars_returned`
  effectively 0. The bytes are empty → nothing to materialize.
- **`1mo` (3,375 tasks): ~3,364 empty (EODHD), ~10 non-empty (EODHD).** Note these went to **EODHD**,
  not Yahoo — the result of zero-bar failover (5 consecutive Yahoo empties → fall back to EODHD per
  `routing.py:_fallback_provider`), and EODHD's demo/limited key returns empty for monthly too.

**Why the empties:** the scheduler issues *incremental, watermark-bounded* polls. For a 12h/24h
weekly/monthly cadence the requested `[start, end]` window is typically a single recent day — and a
weekly bar only "closes" on Fridays, a monthly bar on month-end — so Yahoo returns 0 rows for almost
every poll. The polling cadence/window is fundamentally mismatched to weekly/monthly bar semantics.

---

## 4. The bars API endpoint — where the chain stops

**Endpoint:** `GET /api/v1/ohlcv/bars` (`market-data/.../api/routers/ohlcv.py:77-141`).

- Accepts `interval` with regex `^(1m|5m|15m|30m|1h|4h|day|week|month)$` (`ohlcv.py:85`).
  So `week`/`month` are **accepted (no 400)**.
- The router docstring claims "interval resampling (day/week/month) handled server-side"
  (`ohlcv.py:95`). **This is false.**
- It calls `GetOHLCVBarsFlexibleUseCase.execute(...)`
  (`use_cases/get_ohlcv_bars_flexible.py:32-99`). That use case maps
  `week → Timeframe.ONE_WEEK`, `month → Timeframe.ONE_MONTH`
  (`get_ohlcv_bars_flexible.py:55-66`) and then does a **plain table read**:
  `ohlcv_read.find_by_instrument_timeframe_range(iid, timeframe, from, to)`
  (`get_ohlcv_bars_flexible.py:69-74`). **No derivation, no fallback.**
- Since `ohlcv_bars` has zero `1w`/`1M` rows, the result is `{"bars": [], "bar_count": 0}`.
  **Silent empty — not a 400.** This is exactly why the chart's 5Y view was blank and got dropped.

**The chain stops here:** the endpoint maps the interval correctly but reads an empty table, and
**never calls the derive logic** that would have produced bars from the 274 daily NVDA rows.

S9 (`api-gateway/routes/market.py`, `clients/market.py`) is a transparent proxy of the bars
endpoint — it forwards `interval` verbatim and has no resample of its own (consistent with the
chart engineer's finding). So S9 is not the break; it faithfully relays the empty S3 response.

### Secondary bug — `1mo` → `1d` silent mislabel (S3 consumer)

`ohlcv_consumer.py:272-276`:
```python
try:
    tf = Timeframe(timeframe_str)
except ValueError:
    tf = Timeframe.ONE_DAY
```
The `Timeframe` enum has `ONE_MONTH = "1M"` (`domain/enums.py:19`) — there is **no `"1mo"` member**.
S2 publishes `timeframe="1mo"` for monthly. So `Timeframe("1mo")` raises `ValueError` and the
consumer **silently coerces monthly bars to `ONE_DAY`**, contaminating the daily series. (`1w`
*is* a valid member, so weekly would label correctly — but weekly payloads are empty anyway.)
Even if monthly ingestion were fixed upstream, this coercion would corrupt it. The empty-payload
content-hash dedup (`ohlcv_consumer.py:170-174`) further guarantees the empty `1w`/`1mo` events are
skipped.

---

## 5. What's MISSING — precise categorization

1. **BUILT-BUT-NOT-EXPOSED (primary):** `GetOrDeriveOHLCVBarsUseCase` + `DeriveOHLCVUseCase` are
   complete and correct but wired to **no router/worker/consumer**. The live bars endpoint uses a
   *different* use case (`GetOHLCVBarsFlexibleUseCase`) that does a raw table read and never
   derives. The aggregation logic exists; the request path doesn't use it.
2. **BUILT-BUT-NOT-RUN (secondary):** The derived-bar cache (`is_derived` weekly/monthly rows) is
   never populated because nothing schedules the derive, and the on-demand path that would
   lazily populate it isn't wired either. Table stays empty.
3. **INGESTION DEAD-END (tertiary, not the right fix):** S2 *does* schedule `1w`/`1mo` polls, but
   they return empty payloads (Yahoo window too narrow; EODHD demo unsupported), so even the
   "polling" design produces nothing. Plus the `1mo`→`1d` enum-coercion bug would mislabel any real
   monthly data that did arrive.

Net: the chart receives an empty array for `interval=week|month`, with no error, so the frontend
dropped 5Y.

---

## Ranked fix plan

### P0 — Wire the existing on-demand derive into the bars endpoint (highest leverage)

Make `GET /api/v1/ohlcv/bars` (the endpoint the chart uses) call `GetOrDeriveOHLCVBarsUseCase` for
`week`/`month` instead of the raw-read `GetOHLCVBarsFlexibleUseCase`. The derive logic already
exists, is tested (PLAN-0036), and NVDA-class symbols have ample daily history to derive from
immediately. Two clean shapes:

- **(a) On-the-fly resample at query time (no storage cost):** for `interval in {week,month}`,
  aggregate the daily bars in the requested range in-memory and return — fully stateless, zero new
  rows. Trivially correct for charts; recompute cost is tiny (≤~260 daily bars → ~52 weekly).
- **(b) Cache-or-derive (uses `is_derived` rows):** call `GetOrDeriveOHLCVBarsUseCase` which
  populates and reuses derived rows. Lower repeat-query cost, but writes derived rows on the read
  path (needs a write UoW — conflicts with R27 read-replica-only reads).

**Recommendation: (a)** — pure query-time resample of daily bars for `week`/`month`. No storage
growth, no write-on-read, no R27 violation, no dependency on the broken ingestion path. This is the
single change that unblocks the 5Y chart. Also fix the router docstring ("handled server-side") to
match reality. Cap source-day fetch by `max_bars × bucket-size` to bound the resample.

### P1 — Fix the `1mo` → `1d` silent enum coercion (data-integrity, prevents future corruption)

In `ohlcv_consumer.py:272-276`, normalize `"1mo"` → `ONE_MONTH` (or add a `"1mo"` alias to the
`Timeframe` enum) and **dead-letter unknown timeframes instead of silently coercing to `ONE_DAY`**.
The current fallback poisons the daily series with any mislabeled coarse bar and is invisible.
(BP-worthy: "silent enum-coercion to a wrong-but-valid value.")

### P2 — Decide the ingestion strategy: kill the dead weekly/monthly polls OR fix the window

The S2 `1w`/`1mo` polling policies generate ~7,000 empty "successful" tasks (noise, Kafka traffic,
watermark churn) and produce nothing usable. Once P0 derives weekly/monthly from daily locally
(the original PLAN-0036 intent), the polling path is redundant. Either:

- **Remove/disable** the `1w` + `1mo` polling policies (migration), keep only `1d` ingestion +
  local derive — *aligns with PLAN-0036, recommended*; or
- If polled weekly/monthly is genuinely wanted, fix the scheduler to request a **wide enough window**
  (multi-month) for weekly/monthly and a provider that actually serves them (real EODHD key or
  Yahoo with full range), AND fix P1 so monthly isn't mislabeled.

**Tradeoffs:** P0(a) = zero storage, small per-request CPU, no R42/R27 issues, unblocks the chart
immediately and independently of ingestion. A continuous aggregate / scheduled rollup (the
"materialize once" alternative) costs storage + a new scheduled job and only pays off at very high
query volume — overkill for a chart endpoint. **Highest-leverage single action: P0(a).**

---

## Evidence index (read-only)

- Derive logic: `derive_ohlcv.py:50-212`, `get_or_derive_ohlcv.py:28-148`.
- Intraday-only resample ceiling: `resample_ohlcv.py:_PERIOD_SECONDS` (max `ONE_DAY`).
- Unwired (no router/worker references): grep of `services/market-data/src`.
- Live bars endpoint + false docstring: `api/routers/ohlcv.py:77-141` → `get_ohlcv_bars_flexible.py:55-74` (raw read, no derive).
- Enum coercion bug: `ohlcv_consumer.py:272-276`; enum `domain/enums.py:11-19` (no `1mo`).
- Empty-payload dedup: `ohlcv_consumer.py:170-174`.
- DB intervals: `psql market_data_db` — distinct timeframes `{1m,5m,15m,30m,1h,4h,1d}`, zero `1w`/`1M`; NVDA per-interval counts above.
- Empty ingestion payloads: `psql ingestion_db` — `1w`/`1mo` succeeded tasks dominated by empty SHA `e3b0c442…`; routing `strategies/routing.py:24,42-66`; policy seeds `0002_initial_seeds.py:191,263`.
