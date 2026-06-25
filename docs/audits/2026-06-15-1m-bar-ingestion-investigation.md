# 1-Minute OHLCV Bar Ingestion Investigation

**Date:** 2026-06-15 (Sunday — US markets closed; last trading session = Fri 2026-06-12)
**Scope:** READ-ONLY. No code/DB/container mutations. Code reading + `docker logs` + `psql` SELECTs + S9 curl (dev-login).
**Reported symptom:** AAPL (instrument `01900000-0000-7000-8000-000000001001`) has zero recent 1m bars; `market-data:8003/api/v1/ohlcv/bars?interval=1m&symbol=AAPL` returns 200-empty; S9 `/v1/instruments/AAPL/candles` + `/v1/market/AAPL/quote` return 404; NVDA/TSLA "work". User expected 1m ingestion to resume after the content-ingestion dispatcher restart.

---

## TL;DR — Root Cause

**There is NO 1m-ingestion outage and NO AAPL-specific data gap.** Three independent
mis-diagnoses are stacked in the symptom:

1. **The 1m pipeline is fully healthy and actively running right now.** Alpaca-1m tasks
   are succeeding every minute (last success `2026-06-15 19:21`), the outbox dispatcher is
   delivering, and the market-data `ohlcv-consumer` is materializing 100–1000 bars/symbol
   *live* (observed at `19:22`). This is a **completely separate pipeline** from the
   `content.article.raw.v1` news dispatcher that was restarted — restarting the news
   dispatcher has no bearing on OHLCV.

2. **Bars look "stale" because today is Sunday.** The newest 1m `bar_date` across the whole
   table is `2026-06-12 19:54Z` (Friday). Alpaca returns the **last trading session**; with
   the market closed Sat/Sun there is simply no newer 1m data to fetch. "Zero instruments in
   the last 24h" is the correct, expected weekend state — not a wedged producer.

3. **AAPL is NOT missing 1m data** — it has **1,466** 1m bars (333 on Friday alone), more
   Friday bars than NVDA (4) and on par with TSLA (329). AAPL is enabled in the 632-symbol
   Alpaca-1m polling set at priority 100, identical to the symbols that "work".

4. **The S9 404s are non-existent routes, not resolution failures.** `/v1/instruments/{symbol}/candles`
   and `/v1/market/{symbol}/quote` **do not exist anywhere in api-gateway**. They 404 for
   AAPL, NVDA **and** TSLA equally (verified live). The real S9 routes are
   `/v1/ohlcv/{instrument_id}` and `/v1/quotes/{instrument_id}`, keyed by the **instrument
   UUID, not a ticker** — both return **200** with AAPL Friday 1m data.

5. **The "200-empty" on `market-data /ohlcv/bars?interval=1m&symbol=AAPL`** is a caller error:
   that endpoint **requires `from_date` and `to_date`** (no defaults) and defaults
   `interval=day`. A call with no/now-anchored date range returns empty because the latest
   data is Friday — supply `from_date`/`to_date` covering 06-12 and the bars appear.

**Highest-leverage action:** none on the pipeline. Fix the *callers* (chat tool + quote-tab
chart) to (a) use the UUID-keyed S9 routes, and (b) anchor the date window on the last
trading session rather than `now()`. Optionally add a "market closed / last session" UX state.

---

## Evidence

### Pipeline is live (market-ingestion S2 → Kafka → market-data S3)

`ingestion_db.ingestion_tasks`, provider=alpaca timeframe=1m:

| status | count | last_completed | last_created |
|--------|------:|----------------|--------------|
| succeeded | 121,547 | **2026-06-15 19:21:13Z** | 2026-06-15 19:20:56Z |
| failed | 10 | 2026-06-03 02:54 (stale) | 2026-06-03 00:11 |

market-data `ohlcv-consumer` logs (last 1h: 735 lines), live materialization at 19:21–19:22:
`ohlcv_consumer.materialized` with `bar_count` 105–1099 per symbol (ASML 361, IWM 368, …).
→ Ingestion fetches, dispatcher delivers, consumer writes. **No wedged producer.**

### 1m freshness — whole feed, not AAPL (`market_data_db.ohlcv_bars`)

Overall by timeframe (bars in last 7d):

| timeframe | bars | max bar_date |
|-----------|-----:|--------------|
| 1m | 244,550 | **2026-06-12 19:54Z** |
| 5m | 39,276 | 2026-06-12 14:35Z |
| 1d | 2,278 | 2026-06-12 00:00Z |

Distinct instruments with a 1m bar in the **last 24h: 0** — expected (weekend).
1m bars exist for the trading days **06-10, 06-11, 06-12** only; nothing after Friday.

### AAPL vs NVDA vs TSLA — the key comparison

| symbol | instrument_id present? | has_ohlcv | in 1m polling set (pri/enabled)? | 1m bars total | max 1m bar | Friday (06-12) 1m bars |
|--------|:---:|:---:|:---:|---:|---|---:|
| **AAPL** | yes (`…1001`) | t | yes (100 / enabled) | **1,466** | 2026-06-12 18:48Z | **333** |
| **NVDA** | yes (`…1006`) | t | yes (100 / enabled) | 1,126 | 2026-06-12 13:32Z | **4** |
| **TSLA** | yes (`…1004`) | t | yes (100 / enabled) | 1,416 | 2026-06-12 18:48Z | 329 |

AAPL has the **most** Friday 1m bars of the three. The premise ("AAPL zero, NVDA/TSLA work")
is not supported by the data. Polling policies: 632 enabled `alpaca/1m` rows, all priority 100
(commit `7a4947faa` migration `0018` bumped these 20→100; verified applied — H-1 healthy).

### S9 route reality (api-gateway `routes/market.py`)

Live curl through S9 (fresh dev-login token), all three symbols:

| URL | AAPL | NVDA | TSLA |
|-----|:---:|:---:|:---:|
| `/v1/instruments/{sym}/candles` | 404 | 404 | 404 |
| `/v1/market/{sym}/quote` | 404 | 404 | 404 |
| `/v1/ohlcv/{UUID}?timeframe=1m` | **200** | — | — |
| `/v1/quotes/{UUID}` | **200** | — | — |

- `grep -rn 'candles' services/api-gateway/src` → **zero matches**. No candles route exists.
- Real OHLCV/quote routes are UUID-keyed: `market.py:1293 @router.get("/ohlcv/{instrument_id}")`,
  `market.py:1639 @router.get("/quotes/{instrument_id}")`.
- 200 payload for `/v1/ohlcv/01900000-0000-7000-8000-000000001001?timeframe=1m` returns AAPL
  1m bars with `bar_date` 2026-06-12T18:46–18:48Z, `source: alpaca`. Data present and correct.

### market-data `/ohlcv/bars` "200-empty" explained

`services/market-data/src/market_data/api/routers/ohlcv.py:77-105`: the flexible
`GET /ohlcv/bars` endpoint **requires `from_date` and `to_date`** (no defaults; line 83-84)
and defaults `interval=day` (line 85). It resolves `symbol=AAPL` fine via
`InstrumentLookupUseCase` (would 404 only on a genuinely unknown ticker). A call that omits
or `now()`-anchors the date range returns an empty `bars[]` because the newest 1m data is
Friday — a **caller windowing bug**, not missing data.

---

## Why each part of the symptom happened

| Symptom | Reality |
|---------|---------|
| "AAPL has zero recent 1m bars" | False. AAPL has 1,466 1m bars incl. 333 Friday. "Recent" = today/Sunday, when no symbol has bars (market closed). |
| "`/ohlcv/bars?interval=1m&symbol=AAPL` 200-empty" | Endpoint requires `from_date`/`to_date`; without a Friday-covering window it returns empty. Provide the date range → bars appear. |
| "S9 candles + quote 404 for AAPL, NVDA/TSLA work" | The candles/quote-by-symbol routes don't exist. 404 is uniform across all tickers. Real routes are UUID-keyed and return 200. |
| "expected 1m to resume after dispatcher restart" | Unrelated pipeline. 1m never stopped; it's just the weekend. |

---

## Ranked Fix Plan

### P0 — Fix the callers (single highest-leverage action)
The chat tool and quote-tab intraday chart are calling **non-existent S9 routes**
(`/v1/instruments/{symbol}/candles`, `/v1/market/{symbol}/quote`). Repoint them to the real
contract:
- Resolve ticker→`instrument_id` first (e.g. `/v1/instruments/lookup` or the companies/by-ticker
  overview route), then call `GET /v1/ohlcv/{instrument_id}?timeframe=1m` and
  `GET /v1/quotes/{instrument_id}`.
- For the temporal `/ohlcv/bars` endpoint, always pass `from_date`/`to_date`, and anchor the
  window on the **last trading session** (look back ≥3 days to clear a weekend), not `now()`.

### P1 — UX / "no live data" affordance
Quote-tab and chat should detect "market closed / showing last session (Fri 06-12)" and label
the chart accordingly instead of rendering as empty/error. Surface `max(bar_date)` so the UI
can show "as of …".

### P2 — Observability + premise hygiene
- Add a "1m freshness vs last trading session" metric/alert (freshness relative to the market
  calendar, not wall-clock), so weekend staleness is not mistaken for an outage and a *real*
  weekday stall is caught.
- Re-validate any monitoring/runbook that asserts "AAPL has no 1m / NVDA-TSLA work" — that
  comparison is factually inverted (AAPL has more Friday bars than NVDA).

### Non-actions (confirmed healthy — do NOT touch)
- Alpaca-1m polling policies (632 enabled, priority 100, migration 0018 applied).
- market-ingestion worker / dispatcher (succeeding every minute).
- market-data ohlcv-consumer (materializing live).
- No wedged-producer / stuck-outbox condition exists on the OHLCV path.

---

## Commands used (read-only, reproducible)
```sql
-- freshness
SELECT timeframe,count(*),max(bar_date) FROM ohlcv_bars WHERE bar_date>now()-interval '7 days' GROUP BY timeframe;
-- AAPL/NVDA/TSLA 1m
SELECT i.symbol,count(*),max(b.bar_date),count(*) FILTER (WHERE b.bar_date::date='2026-06-12')
FROM ohlcv_bars b JOIN instruments i ON i.id=b.instrument_id
WHERE b.timeframe='1m' AND i.symbol IN ('AAPL','NVDA','TSLA') GROUP BY i.symbol;
-- policies (ingestion_db)
SELECT provider,timeframe,count(*),max(priority),count(*) FILTER (WHERE enabled) FROM polling_policies GROUP BY 1,2;
-- live tasks (ingestion_db)
SELECT status,count(*),max(completed_at) FROM ingestion_tasks WHERE provider='alpaca' AND timeframe='1m' GROUP BY status;
```
```bash
docker logs worldview-market-data-ohlcv-consumer-1 --since 1h   # live ohlcv_consumer.materialized
TOK=$(curl -s -X POST :8000/v1/auth/dev-login -d '{}'| jq -r .access_token)
curl :8000/v1/instruments/AAPL/candles      # 404 (route does not exist)
curl :8000/v1/ohlcv/01900000-0000-7000-8000-000000001001?timeframe=1m  # 200 + Friday bars
```
