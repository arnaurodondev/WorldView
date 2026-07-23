# Consolidated intraday volume across timeframes — architecture review

**Date:** 2026-07-16
**Branch:** `feat/consolidated-volume-timeframes`
**Scope:** READ-ONLY investigation + recommendation. No pipeline change deployed.
**Question (operator):** Daily OHLCV volume is now correct (EODHD bulk-EOD =
consolidated). But intraday timeframes (5m/15m/30m/1h/4h) are derived from
**Alpaca free-tier 1m, which is IEX-only (~2–5% of consolidated volume)**, so
every intraday bar carries ~5% volume. Should we source a
correct-consolidated-volume **base** intraday timeframe and derive **all**
timeframes up from it (the pattern we already use for Alpaca 1m), so volume is
correct and consistent everywhere?

---

## TL;DR / Recommendation

**Keep Option A (status quo). Do not spend money and do not add a fabricating
scale-factor now.** Absolute intraday volume in this product is **cosmetic-only**:
it is displayed on exactly one surface (the 1D/5D instrument chart's volume
histogram + crosshair tooltip, which render from 5m bars) and it is *not* an
input to any signal, screener filter, ranking, session-volume statistic, or
KG/RAG computation. Every one of those already reads the **correct** consolidated
**daily** volume (or a volume-*weighted ratio* like VWAP that is invariant to the
~5% scaling).

If correct absolute intraday volume ever becomes a real product requirement, the
cheapest correct upgrade is a **one-env-var Alpaca SIP switch** (`alpaca_feed=sip`,
already wired — needs the $99/mo Algo Trader Plus subscription), which makes the
*existing* bulk 1m pull consolidated with **zero code change**. That is the clean
"single correct-volume base → derive all" architecture the operator described.
Polygon (~$29/mo, adapter already in-tree, keyed-off today) is the cheaper paid
alternative. Both are unjustified for a thesis/demo today.

**I implemented nothing in the data pipeline** — see "Why no code change" below.

---

## 1. How timeframes are derived today (confirmed)

Two independent derivation paths, both pure `open=first / high=max / low=min /
close=last / volume=SUM(source volumes)` aggregation:

| Path | File | Source → targets |
|---|---|---|
| Intraday resampling (event-driven, on each 1m batch) | `services/market-data/.../use_cases/resample_ohlcv.py` (`ResampledOHLCVUseCase.execute` / `execute_batch`) | **Alpaca 1m → 5m/15m/30m/1h/4h** via `bulk_upsert_derived`. `_DEFAULT_TARGET_TIMEFRAMES` deliberately **stops at 4h** — 1d is NOT derived here. |
| Daily→weekly/monthly (query-time, in-memory) | `services/market-data/.../use_cases/derive_ohlcv.py` (`derive_bars_in_memory`) | **1d → 1w/1M** (ISO-week Monday / month-day-1 anchors). |

Volume-sum propagation is confirmed in both:
`resample_ohlcv.py:127` (`volume=sum((b.volume or 0) for b in source_bars)`) and
`derive_ohlcv.py:82`. **Therefore any error in the 1m base volume propagates,
unchanged in ratio, into 5m…4h.** IEX ≈ 5% of consolidated ⇒ every intraday bar
is ≈ 5% of true volume.

**Final topology (PLAN-0036), per code comments and routing config:**
- `1m` (base intraday) — **Alpaca, free, IEX feed**, bulk (multi-symbol up to
  1000/call), `alpaca_feed="iex"` (`market-ingestion/config.py:60`).
- `5m…4h` — **derived** from 1m (authoritative, priority 110).
- `1d` — **polled** directly (`routing_ohlcv_eod = "alpaca:100,eodhd:80"`);
  EODHD bulk-EOD is the correct consolidated daily volume (the in-flight fix).
- `1w/1M` — derived-on-read from `1d`.

So each timeframe family has exactly one source. The **only** family with wrong
volume is the intraday one (1m…4h), because its single source is IEX.

Prod bar inventory (market_data_db, 2026-07-16): `1d` 323,850 · `1m` 64,792 ·
`5m` 16,759 · `15m` 5,871 · `30m` 2,998 · `1h` 1,603 · `4h` 453. 561 instruments
(530 US).

---

## 2. Does the product need correct ABSOLUTE intraday volume? — the crux

Swept `apps/worldview-web`, `market-data`, and `knowledge-graph` for every
consumer of intraday volume. Findings:

| Surface | Reads intraday volume? | Correct today? | Notes |
|---|---|---|---|
| **1D / 5D instrument chart** volume histogram + crosshair tooltip (`components/instrument/chart/*`, `createChartSeries.ts`) | **YES — absolute** | ❌ ~5% | The 1D/5D periods are the *only* ones that map to intraday bars: `chartPeriods.ts` routes `1D/5D → "5M"` and every longer period (`1M/3M/6M/1Y → "1D"`, `5Y/MAX → "1W"`) to **correct** daily-derived data. The histogram is a *relative* visual — the bar-to-bar *shape* is preserved (uniform ~5% scaling), only the y-axis absolute numbers and the hovered value are ~20× low. |
| **VWAP** — Quote tab intraday stats (`query_quote_stats.py:104` `GetIntradayStatsUseCase`) + chart VWAP overlay | YES, but as a **volume-weighted ratio** | ✅ ~correct | `VWAP = Σ(typical·vol)/Σ(vol)`. Scaling every `vol` by the same IEX fraction cancels. Robust to IEX (assuming ~uniform intraday IEX share, which holds well enough). |
| **Session volume** (IntradayStatsStrip / `volume_vs_30d_ratio`) | Uses the **DAILY** bar's volume, not the intraday sum (`query_quote_stats.py:120`, explicit "the daily bar's volume is authoritative") | ✅ correct | Intraday sum is only a *fallback* when no daily bar exists. |
| **Screener** `volume` column + `avg_volume_30d` filter | Daily `volume` / EODHD Technicals `avg_volume_30d` | ✅ correct | No intraday input. |
| **Returns / price levels / 52w / MA50-200 / S-R** | Daily bars only | ✅ correct | Price-only; no volume. |
| **Knowledge-graph / RAG signals** | No equity intraday volume anywhere. "volume" in KG = *news* volume; `prediction_move_detector` uses *Polymarket* USD volume | n/a | Confirmed: no momentum/liquidity signal consumes equity intraday volume. |

**Conclusion:** correct absolute intraday volume matters for **one cosmetic
surface** (1D/5D chart histogram + crosshair). It feeds **no** signal, filter,
ranking, or the authoritative session-volume stat, and VWAP is already robust.
This is a **low-stakes** correctness gap. Daily/weekly/monthly volume — the
resolution shown for every chart period except 1D/5D — is already correct.

---

## 3. Source-option matrix (correct-consolidated intraday, bulk/cheap)

| Source | Exists / keyed? | Bulk or per-ticker? | Consolidated volume? | History | Cost | Notes |
|---|---|---|---|---|---|---|
| **Alpaca IEX 1m** (current) | ✅ live | **Bulk** (≤1000 sym/call, ~3 calls/min all tickers) | ❌ IEX only (~2–5%) | ~6y daily / rolling intraday | **$0** | Free real-time-ish. The reason intraday volume is wrong. |
| **Alpaca SIP 1m** | Config already wired (`alpaca_feed`, `market-ingestion/config.py:60`); needs subscription | **Bulk** (same endpoint) | ✅ full consolidated | same | **$99/mo** (Algo Trader Plus) | **One env-var flip** makes the *existing* bulk pull consolidated. Best "single base → derive all" fit, zero code. |
| **EODHD intraday** `/intraday/{sym}?interval=1m` | ✅ **already coded** (`eodhd.py:251` `fetch_intraday`, `EODHD_INTRADAY_COST=5`), but **NOT in intraday routing** (`routing_ohlcv_intraday="alpaca:100,polygon:80"`) | **Per-ticker** (single symbol/request), 5 calls each | ✅ **1m = consolidated CTA/UTP feed** (all US exchanges, incl. pre/post; per EODHD docs, ref line 4205). *5m is single-venue* — must use **1m**. | Default last 120 days | **$0 extra** (on current EODHD plan; consumes 100k/day budget) | 530 US × 5 = **2,650 calls/full sweep**. Once/day post-close (finalizes 2–3h after close) = trivial; live/frequent polling (e.g. every 15m × 26 = ~69k/day) risks the 100k/day cap. Per-ticker + budget management = real added complexity. Data is unadjusted (splits handled elsewhere — fine intraday). |
| **Polygon** (Massive) v2 aggs | Adapter in-tree (`polygon.py`, intraday routing priority 80) but **no API key** (`polygon_api_key=""` ⇒ disabled) | **Per-ticker** aggs (grouped-daily is bulk; intraday is single-ticker) | ✅ aggregates are full consolidated SIP tape (tier gates *recency*, not consolidation) | 5–15+ yr by tier | **~$29/mo** Starter (15-min delayed) / ~$79+ real-time | Cheapest paid consolidated intraday. Delayed is fine for charts. Needs key + wiring + backfill. |
| **EODHD EOD-only** (current daily fix) | ✅ live | Bulk-EOD | ✅ daily consolidated | deep | in-plan | Daily correct; intraday untouched (stays IEX). |

Pricing verified 2026-07: Alpaca Algo Trader Plus **$99/mo** (full SIP real-time);
Polygon/Massive Stocks Starter **~$29/mo** (15-min delayed, consolidated
aggregates, unlimited calls).

---

## 4. Architecture options

### Option A — Current hybrid (Alpaca IEX 1m intraday + EODHD-bulk daily volume)
- **Correctness:** intraday absolute volume ~5% (wrong on 1D/5D chart only);
  daily/weekly/monthly correct; VWAP ~correct; no signal affected.
- **Cost:** **$0.**  **Complexity:** none (already shipped).
- Verdict: acceptable given §2 — the wrong numbers are cosmetic and confined.

### Option B — Single correct-volume base intraday → derive daily + all timeframes
Exactly the operator's proposal. Three sub-variants:
- **B1 Alpaca SIP** — flip `alpaca_feed=sip` + subscribe. **Zero code**, bulk,
  real-time, consolidated everywhere (intraday *and* the Alpaca 1Day daily
  becomes consolidated too). **$99/mo.** Cleanest architecture, highest cost.
- **B2 EODHD 1m** — add `eodhd` to `routing_ohlcv_intraday`, schedule a
  per-ticker sweep. **$0 extra** but per-ticker (2,650 calls/sweep), realistically
  a once-daily post-close refinement (not live), plus 100k/day-budget care and a
  new scheduler. Moderate code.
- **B3 Polygon** — add API key, backfill via existing adapter. **~$29/mo**,
  per-ticker, 15-min delayed. Moderate code.
- **Correctness:** ✅ everything correct + consistent. **Complexity:** B1 trivial,
  B2/B3 moderate.

### Option C — Keep free Alpaca IEX shape, SCALE intraday volume to the day's EODHD total
At derive/query time multiply each intraday bar's volume by
`consolidated_daily_total / Σ(IEX_intraday_volume_that_day)`, distributing the
correct daily volume across the day by IEX's intraday shape.
- **Correctness:** daily totals become exact; intraday becomes a *modeled*
  approximation (assumes IEX intraday share ≈ uniform — mostly true, skews at
  open/close). VWAP unchanged (per-day constant scaling cancels).
- **Cost:** **$0.**  **Complexity:** moderate + two real problems:
  1. **Fabrication.** It replaces measured IEX volume with a *modeled*
     distribution. This directly contradicts the codebase's explicit honesty
     contract ("we NEVER fabricate a value", `query_quote_stats.py:7`; returns
     `None` rather than invent). Showing a synthesized intraday volume is
     arguably *less* honest than showing true-but-partial IEX volume.
  2. **Live-day finalization.** The consolidated daily total isn't final until
     2–3h after close, so the current session can't be scaled accurately — the
     one moment a live chart is most watched.

---

## 5. Why no code change was implemented

The task authorized implementing *only if* one option is clearly-correct **and**
cheap. None qualifies:

- **B1 (SIP)** is the trivial one, but the "trivial change" (env-switchable feed)
  is **already in the code** — the only missing piece is a **$99/mo
  subscription**, an operator/billing decision, not code. Nothing to implement.
- **C** is $0 but **fabricates** intraday volume, violating the project's honesty
  invariant, and breaks on the live session. Not clearly-correct.
- **B2/B3** are non-trivial (new scheduler / API key / backfill / per-ticker
  budget) — not "cheap" in effort, and unjustified for a cosmetic gap.

Given §2 (cosmetic-only, nothing downstream depends on it), the correct
engineering answer is to **change nothing in the pipeline now**. The single
honest, zero-cost, in-scope improvement would be a **frontend** one — label the
1D/5D volume histogram as "IEX (partial)" or hide absolute numbers at intraday
resolution — but that is a `worldview-web` change outside this branch's data-layer
scope and is logged here as a follow-up, not implemented.

---

## 6. Recommendation summary

1. **Now:** keep **Option A**. Intraday absolute volume is cosmetic; daily+ is
   correct; VWAP and session-volume are already correct/robust; no signal depends
   on it. Spend $0.
2. **Follow-up (frontend, cheap, honest):** on the 1D/5D chart, mark the volume
   histogram as IEX-partial (or suppress absolute intraday volume), so we never
   *display* a materially-wrong number. Daily/weekly/monthly need no change.
3. **If correct intraday volume becomes a requirement:** flip **Alpaca SIP**
   (`alpaca_feed=sip`, one env var, zero code) at $99/mo for real-time consolidated
   everywhere — this is precisely the "one correct base → derive all" design — or
   key **Polygon** at ~$29/mo for delayed consolidated. **Avoid Option C**
   (fabrication + live-day gap).
</content>
