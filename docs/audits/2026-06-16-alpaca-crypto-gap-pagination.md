# Audit: Alpaca adapter `limit=10000` truncation — bigger than the crypto-gap edge

**Date:** 2026-06-16
**Scope:** READ-ONLY investigation. No code/schema/data changes.
**Service:** `market-ingestion` (S3 ingestion side)
**Trigger:** Reported concern that a 7-day 1m crypto gap (10,080 bars) exceeds the `limit=10000`
page size and the un-paginated Alpaca fetch silently drops the oldest ~80 minutes.

---

## VERDICT

The reported crypto-gap edge is **real but is the smaller half of the bug**. The Alpaca
`limit` parameter is **PER-RESPONSE (total across all symbols combined), not per-symbol** —
confirmed by the official Alpaca docs. Combined with the fact that the adapter **never
follows `next_page_token`**, this means:

- A **single batch HTTP call** that groups multiple symbols can have its entire 10,000-bar
  budget consumed by the **first symbol(s)** in symbol-sorted order, returning **zero bars**
  for the later symbols in the same call — far worse than a clean 80-minute tail loss.
- The crypto-7-day edge (10,080 > 10,000) is just the single-symbol manifestation of the
  same missing-pagination root cause.

Because Alpaca sorts the multi-symbol response **by symbol first, then by timestamp**, and the
adapter reads only page 1, the truncation is **front-loaded onto whichever symbols sort first**
and starves the rest. This is a correctness bug on every multi-symbol intraday batch large
enough to exceed 10k combined bars, not just on the crypto-outage path.

**Recommended fix:** add `next_page_token` pagination to both `fetch_ohlcv` and
`fetch_ohlcv_batch` (loop until the token is absent, accumulate bars, re-key by symbol). This
is the only fix that is fully correct under the per-response limit. Time-range chunking and a
`_MAX_CATCHUP_DAYS` cap are stopgaps that do **not** close the multi-symbol total-limit hole.

---

## 1. Confirming the truncation and the `limit` semantics

### Code facts (`alpaca.py`)

- `fetch_ohlcv` (single symbol, L114–206): builds params with `limit=10000, sort=asc`,
  `start`/`end`. Calls `_get()` **once** (L174), parses page 1 (`_parse_bars`, L416–437), and
  returns. **No `next_page_token` handling anywhere.** The docstring at L425 even shows
  `"next_page_token": null` in the example response shape but the code never reads it.
- `fetch_ohlcv_batch` (L210–307): same — one `_get()` per chunk (L265), reads
  `data.get("bars")` once (L273), distributes to symbols (L275–299). **No pagination.**
- `_BATCH_SIZE = 1000` (L85) is the **HTTP-level** symbol cap (comma-separated `symbols=`),
  matching Alpaca's request-size guidance. It is **not** a bars cap and does nothing to keep a
  multi-symbol response under the 10k *bars* budget.
- `_get` (L472–516) is a plain single GET; it does not loop.

### Alpaca API contract (official docs + community confirmation)

Both the equity and crypto bars endpoints share the same contract:

| Property | `/v2/stocks/bars` | `/v1beta3/crypto/us/bars` |
|---|---|---|
| `limit` max | 10000 (default 1000) | 10000 |
| `limit` scope | **total data points, NOT per symbol** | **total across symbols** |
| Pagination | `next_page_token` → resubmit as `page_token` until null | same (`page_token`) |
| Multi-symbol sort | **by symbol, then by timestamp** | by symbol, then timestamp |

Quote from the official stock-bars reference: *"the limit applies to the total number of data
points, not per symbol"*, and *"you are likely to see only one symbol in your first response if
there are enough bars for that symbol to hit the limit … keep requesting with the
next_page_token … you will eventually reach the other symbols."*

So the hypothesis that "if `limit` is the TOTAL across symbols, almost everything is truncated"
is the **confirmed** reality, not the alternative.

---

## 2. Real exposure

### How many symbols actually land in one HTTP call

The `_BATCH_SIZE=1000` value is misleading for exposure sizing. The real grouping happens in
the worker (`worker.py`):

- `worker_batch_size = 10` (config.py L147; confirmed on the live container env:
  `MARKET_INGESTION_WORKER_BATCH_SIZE=10`).
- The worker claims `batch_size` tasks per loop (`_claim_batch`), then `_try_batch_execute`
  (L241–309) groups the claimed tasks by `(provider, timeframe)` and issues **one
  `fetch_ohlcv_batch` per group** with `symbols = [t.symbol for t in group_tasks]`.
- So a single Alpaca HTTP call typically carries **≤10 symbols** (whatever fraction of the
  10-task claim is same-provider/same-intraday-timeframe), **not 1000**.

This *bounds* the blast radius compared to a hypothetical 1000-symbol call, but does **not**
eliminate it. With day-start `range_start` (and the catch-up extension up to 7 days), 10 × 1m
symbols can easily exceed 10k combined bars:

- 1 trading day of 1m equity bars ≈ 390 bars/symbol → 10 symbols ≈ 3,900 bars (under 10k; OK
  for the normal same-day case).
- A multi-day catch-up at 1m: e.g. 7-day equity ≈ 2,730 bars/symbol → **4 symbols ≈ 10,920**
  already blows the budget; the 5th–10th symbols in symbol-sorted order get **0 bars**.
- 1m crypto (1440 bars/day, 24/7): a single 7-day crypto symbol = 10,080 > 10,000 (the
  reported edge); **two** 7-day crypto symbols in one call = 20,160, so symbol #2 is almost
  entirely dropped.

### Live symbol counts (ingestion_db, 2026-06-16)

```
provider='alpaca' AND timeframe='1m' AND enabled=true
  total : 632
  crypto: 29   (symbol LIKE '%-USD')
  equity: 603
```

So 603 equity + 29 crypto 1m policies are exposed. On a normal same-day tick the equity case
stays under 10k per 10-symbol group, but **any multi-day catch-up** (the exact scenario Fix D
in `schedule_tasks.py` was built for) pushes 1m groups over the per-response limit and silently
zeroes the tail symbols. The 29 crypto policies are exposed even on a single ≥7-day gap, and
exposed for ≥2 crypto symbols grouped together at much smaller gaps.

> Note: the symbol-sort ordering means the loss is deterministic, not random — symbols that
> sort earliest alphabetically always win the budget; later symbols starve. That can make the
> gap look like a "some symbols never update" pattern rather than a uniform tail-truncation.

---

## 3. Does the consumer/watermark side compound it? — YES, the hole is permanent

The watermark advancement makes the truncation **non-self-healing**:

- `pipeline.py` `_advance_watermark` (L344–384) computes the new high-water mark as
  `new_ts = min(task.range_end, utc_now())` (L374) — i.e. from the **requested range_end**, NOT
  from the timestamp of the last bar actually returned. So even when the fetch dropped the
  oldest window (or returned 0 bars for a starved symbol that *did* get a non-empty page-1 for
  some other call), the watermark jumps to the requested end.
- `watermark.advance_bar_ts` (domain entity, L53–57) enforces **strict monotonic increase** —
  `new_ts <= current_bar_ts` raises `WatermarkViolation`. Once the watermark has moved past the
  gap, the scheduler can never set a `range_start` back into the dropped window.
- The catch-up logic itself (`_build_incremental_task`, L282–285) resumes `range_start` from
  `watermark.current_bar_ts` (bounded by `_MAX_CATCHUP_DAYS`). Since the watermark already
  advanced past the dropped oldest minutes, the next fetch's `range_start` is *newer* than the
  hole. **The dropped oldest window is never re-requested.**

Net: a mid-gap hole (oldest minutes of a catch-up, or a starved tail symbol) becomes a
**permanent** void in OHLCV history. The ohlcv-consumer materializes whatever the dataset
contains, so it faithfully persists the truncated data and never knows bars are missing.

---

## 4. Recommended fix (ranked)

### (A) Add `next_page_token` pagination — the correct fix. **DO THIS.**

Loop the GET until no token, accumulating bars, then distribute by symbol. Sites:

- `_get` (or a new `_get_paginated`) in `alpaca.py`: after each response, read
  `data["next_page_token"]`; if non-null, re-issue the **same** params plus
  `page_token=<token>` and merge the returned `bars` map (extend each symbol's list).
  Stop when the token is null/absent.
- Apply in **both** `fetch_ohlcv` (L174) and `fetch_ohlcv_batch` (L265). For the batch case,
  merge per-symbol lists across pages before `_normalize_bars`/result construction (L275–299).
- Correctness notes:
  - The param key for the follow-up is `page_token` (request) vs `next_page_token` (response)
    — do not reuse the response key name as the request key.
  - Keep `sort=asc` so accumulated bars stay in order; merging is a simple list-extend per
    symbol because Alpaca pages within a symbol before moving to the next symbol.
  - Add a sane page cap (e.g. ≤ N pages) + structured log to avoid an unbounded loop if Alpaca
    ever returns a self-referential token (a known historical Alpaca quirk surfaced in the
    community forum: "requested 10k bars but only returns 404 with next_page_token").
  - Forward-compatible: purely additive to the adapter; no schema/event/DB change; callers
    (`worker.py`, `execute_task.py`) are unchanged.

### (B) Day-by-day (or fixed-window) time-range chunking for 1m — complementary hardening.

Issue one request per bounded sub-window so each stays well under 10k, then concatenate. Useful
defense-in-depth and bounds memory/latency, but **on its own does not fix the multi-symbol
per-response total** (10 symbols × 1 day of 1m ≈ 3,900 is fine, but more symbols or wider
windows still combine over 10k). Best used together with (A), or as the structure that makes
(A)'s per-window page count small. Site: `_build_incremental_task` window construction
(`schedule_tasks.py` L273–303) and/or a chunk loop inside the adapter.

### (C) Cap `_MAX_CATCHUP_DAYS` — stopgap ONLY, and incomplete.

`_MAX_CATCHUP_DAYS = 7` (schedule_tasks.py L69). For 1m crypto, 6 days = 8,640 < 10,000, so
`≤6` keeps a **single** crypto symbol under the limit. But:
- It does **not** help the per-response total when ≥2 symbols are grouped (2×6-day crypto =
  17,280 > 10k).
- It does **not** help 1m equity multi-day catch-up where 4+ symbols per group already exceed
  10k at the current 7-day cap.
- It silently shrinks the catch-up window the platform was explicitly designed to backfill
  (the 2026-06-13..15 outage comment at L60–68), trading one bug for reduced recovery.

Use (C) only as a same-day mitigation while (A) is being shipped; it is not a real fix.

### Effort/correctness summary

| Fix | Correctness | Effort | Invasiveness |
|---|---|---|---|
| (A) pagination | Full | Medium (adapter-local loop + per-symbol merge + tests) | Low — adapter only |
| (B) range chunking | Partial (needs A for multi-symbol) | Medium | Low/Med — scheduler or adapter |
| (C) cap catch-up days | Partial stopgap | Trivial (one constant) | Trivial — but reduces recovery |

---

## Key files / line references

- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py`
  - `fetch_ohlcv` L114–206 (single GET L174, no pagination)
  - `fetch_ohlcv_batch` L210–307 (single GET per chunk L265, `bars` read L273, distribution L275–299)
  - `_BATCH_SIZE = 1000` L85 (HTTP symbol cap, NOT a bars cap)
  - `_parse_bars` L416–437, `_normalize_bars` L439–470, `_get` L472–516
- `services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py`
  - `_MAX_CATCHUP_DAYS = 7` L69 (comment L59–68)
  - `_build_incremental_task` catch-up window L282–285, range construction L273–303
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py`
  - `worker_batch_size` default 10 (L41), batch grouping `_try_batch_execute` L241–309
    (one `fetch_ohlcv_batch` per provider/timeframe group, `symbols` from claimed batch)
- `services/market-ingestion/src/market_ingestion/application/use_cases/strategies/pipeline.py`
  - `_advance_watermark` L344–384 — watermark from `min(range_end, now)` (L374), not from last bar
- `services/market-ingestion/src/market_ingestion/domain/entities/watermark.py`
  - `advance_bar_ts` strict-monotonic guard L53–57 (prevents re-fetching a passed-over hole)
- `services/market-ingestion/src/market_ingestion/config.py` — `worker_batch_size` L147, `worker_concurrency` L149

## Live data snapshot (ingestion_db, 2026-06-16)

`alpaca` + `1m` + `enabled` policies: **632 total (29 crypto, 603 equity)**.

## Sources

- [Historical bars — Alpaca Docs (`/v2/stocks/bars`)](https://docs.alpaca.markets/us/reference/stockbars)
- [Alpaca Data v2 — Multi-symbol market data request (Alpaca Community Forum)](https://forum.alpaca.markets/t/alpaca-data-v2-multi-symbol-market-data-request/4833)
- [Historical Crypto Data (`/v1beta3/crypto/us/bars`) — Alpaca API Docs](https://docs.alpaca.markets/us/docs/historical-crypto-data-1)
- [Requested 10k bars, but only returns 404 with next_page_token (Alpaca Community Forum)](https://forum.alpaca.markets/t/requested-10k-bars-but-only-returns-404-with-next-page-token/15270)
