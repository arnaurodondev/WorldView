/**
 * components/instrument/chart/chartPeriods.ts — period → fetch-params presets
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 2):
 * The chart toolbar exposes a PERIOD selector (1D / 1W / 1M / 3M / 1Y / 5Y)
 * like TradingView/Finviz, but the S9 price-history endpoint
 * (GET /v1/ohlcv/{id}?timeframe&start) speaks in BAR RESOLUTION ("5M", "1H",
 * "1D", "1W") + a start date. This module is the single source of truth for
 * that translation so OHLCVChart and its tests can never drift apart.
 *
 * DESIGN DECISION — share one fetch per bar resolution, zoom client-side:
 * 1M / 3M / 1Y all map to DAILY bars and share ONE fetch window (366 days).
 * Switching between them therefore:
 *   1. hits the SAME TanStack Query cache slot (qk.instruments.ohlcv(id,"1D"))
 *      → zero refetch, instant switch (requirement 5: tab/period switching
 *      must not refetch);
 *   2. only adjusts the chart's VISIBLE RANGE client-side (see OHLCVChart's
 *      visible-range effect) — lightweight-charts can re-window already-loaded
 *      bars without any network round-trip.
 * 1D / 1W / 5Y need different bar resolutions (5-minute / hourly / weekly), so
 * they get their own cache slots keyed by their timeframe.
 *
 * WHY fetchDaysBack is explicit (not S9's default): S9 injects a default
 * `start` of only 90 days back for daily bars. The 1Y period needs 365 days,
 * so we always pass an explicit start computed from fetchDaysBack.
 */

import type { Timeframe } from "@/lib/chart-adapter";

// ── Period union ─────────────────────────────────────────────────────────────
//
// WHY a string union (not enum): mirrors the Timeframe type convention in
// lib/chart-adapter.ts and lets PeriodSelector (generic over string) infer
// the type without casts.

// ── 2026-06-15 BACKEND-HONEST TIMEFRAME SET (this fix) ───────────────────────
// The previous set (1D/1W/1M/3M/1Y/5Y) advertised periods the S3 market-data
// backend CANNOT serve, which produced all three reported bugs. Verified live
// against S9 → S3 for AAPL (01900000-…-1001) on 2026-06-15:
//
//   timeframe  stored data                          period that used it
//   ─────────  ───────────────────────────────────  ───────────────────
//   5m         ~297 bars over ~1 month (intraday)    1D
//   1h         ~46 bars over ~1 month (SPARSE)       1W  ← only ~10/day
//   1d         274 bars, May-2025 → Jun-2026 (~13mo) 1M / 3M / 1Y
//   1w         0 bars (NOT stored / NOT derived)     5Y  ← always empty!
//   1M(month)  0 bars (NOT stored / NOT derived)     (unused)
//
// ROOT CAUSES of the reported bugs, in backend terms:
//   • "label says X, bars are different / missing"  → 5Y mapped to weekly bars,
//     of which the backend has ZERO, so the 5Y button rendered an empty chart
//     while its label promised 5 years.
//   • "some temporalities missing"                  → 1W (hourly) returns only
//     ~10 bars because the backend stores barely a day of hourly data per day,
//     and 5Y (weekly) returns nothing at all.
//   • "only ~10 bars instead of ~200"              → the 1D/1W intraday fetch
//     WINDOWS were too short (3d / 8d) AND landed on sparse synthetic sessions.
//
// FIX: expose ONLY periods the backend can actually fill, and remove weekly/
// monthly entirely (R14 — the frontend talks only to S9; S3 simply has no
// weekly/monthly bars and no derive path is exposed through S9, so adding a
// backend resample is out of scope and would be a much larger change). The
// daily history is ~13 months, so the longest honest period is 1Y; 6M/3M/1M
// all slice the same daily series. Intraday gets two periods (1D, 5D) over the
// 5-minute series, which is the resolution that actually has dense recent data.
export type ChartPeriod = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y";

/** Display order for the toolbar — shortest to longest, TradingView style. */
export const CHART_PERIODS: readonly ChartPeriod[] = [
  "1D",
  "5D",
  "1M",
  "3M",
  "6M",
  "1Y",
] as const;

// ── Preset shape ─────────────────────────────────────────────────────────────

export interface ChartPeriodPreset {
  /**
   * Bar resolution sent to S9 (?timeframe=). Determines the TanStack cache
   * slot — periods sharing a timeframe share a cache slot (and one fetch).
   */
  readonly timeframe: Timeframe;
  /**
   * How far back the FETCH window reaches (?start=now - fetchDaysBack).
   * Deliberately ≥ visibleDays so client-side zoom-out within the same
   * resolution never needs a refetch.
   */
  readonly fetchDaysBack: number;
  /**
   * How far back the VISIBLE window reaches once data is loaded. The chart
   * sets timeScale().setVisibleRange(lastBar - visibleDays, lastBar).
   *
   * NOTE: this is a CALENDAR-DAY window — for daily/weekly bars markets are
   * closed ~30% of calendar days (weekends/holidays), so `visibleDays` days
   * back contains FEWER than `visibleDays` bars. Prefer `visibleBars` (below)
   * for a precise bar-count window; `visibleDays` stays as the fallback for
   * intraday periods where "one trading session" is naturally a time window.
   */
  readonly visibleDays: number;
  /**
   * OPTIONAL precise bar-count window (Wave-4, 2026-06-12). When set, the
   * chart windows the visible range to the LAST `visibleBars` loaded bars via
   * setVisibleLogicalRange — independent of how many calendar days those bars
   * span. This is what the "default view shows ~200 of ~500 loaded" requirement
   * needs: a day-count window can't promise a bar count because trading days
   * per calendar day vary. When unset, the chart falls back to `visibleDays`.
   */
  readonly visibleBars?: number;
}

// ── Presets ──────────────────────────────────────────────────────────────────
//
// WHY 3 fetch days for the 1D period: a Friday-evening or weekend visit would
// find ZERO bars with a strict 1-day window (markets closed). 3 days always
// spans back to the most recent trading session; the visible range then snaps
// to the most recent session only.
//
// WHY 1830 (one extra day): guards the boundary where "now - 365d" lands
// exactly on the first bar's date and DST/UTC rounding drops it.
//
// ── WAVE-4 FETCH-WINDOW WIDENING (2026-06-12) ────────────────────────────────
// The daily-bar periods (1M/3M/1Y) used to fetch only 366 calendar days back
// (~252 trading days → ~200 daily bars). The redesign goal is "load ~500 bars
// so panning back has real history, show ~200 in the default view". A 366-day
// window can NEVER load 500 bars at daily resolution, so the shared daily-bar
// fetch window is widened to ~730 calendar days (≈ 500 trading days). The S3
// endpoint serves whatever exists up to that window (273 daily bars in the
// current dev dataset; ~500 for a fully-backfilled instrument). All three
// daily periods MUST keep the SAME fetchDaysBack so they share one cache slot
// (the no-refetch-on-period-switch invariant — chartPeriods.test.ts pins it).
//
// WHY 1Y is the DEFAULT now (was 1D): the old default "1D" period maps to
// 5-minute intraday bars over a 3-day window. The dev intraday store holds
// only ~71 such bars and `visibleDays: 1` then windowed that down to a single
// session — the sparse ~10-30 candle band the user reported. The default view
// should show a meaningful price history with room to pan; daily bars deliver
// that. The chart's initial selected period is set in OHLCVChart's useState.

/** The period the chart opens on — daily bars, ~200 visible of the full window. */
export const DEFAULT_CHART_PERIOD: ChartPeriod = "1Y";

/**
 * Shared fetch window for EVERY daily-bar period (1M / 3M / 6M / 1Y).
 *
 * WHY they MUST share one number: identical (timeframe="1D", start) params →
 * identical query-string → ONE TanStack Query cache slot. Switching among the
 * daily periods is then a pure client-side zoom (the visible-range effect in
 * OHLCVChart re-windows already-loaded bars) with ZERO refetch. If two daily
 * periods used different fetchDaysBack they'd serve a DIFFERENT cached series —
 * the exact "label says one thing, bars are another" desync this fix removes.
 *
 * WHY 730 (≈ 500 trading days): the daily series is the deepest the backend
 * has (~13 months ≈ 274 bars today, but a fully-backfilled instrument can hold
 * ~500). 730 calendar days lets the daily window return everything available
 * so the 1Y default opens on the last ~200 bars with the rest loaded behind it
 * to pan through. limit=1000 (sent from OHLCVChart) is the hard ceiling.
 */
const DAILY_FETCH_DAYS_BACK = 730;

/**
 * Shared fetch window for the two intraday (5-minute) periods (1D / 5D).
 *
 * WHY they share it (same rationale as the daily window): 1D and 5D both map
 * to the "5M" resolution, so giving them the SAME fetchDaysBack means they
 * share ONE cache slot and switching between them is a client-side re-window,
 * not a refetch.
 *
 * WHY 8 calendar days (was 3 for the old 1D): the live 5-minute store holds
 * ~1 month of bars but individual recent sessions can be sparse/synthetic in
 * dev (verified: 11/60/11 bars on consecutive days). An 8-day window always
 * spans several trading sessions so the 5D view has real width and the 1D view
 * can window down to the most recent dense session — fixing the "only ~10 bars"
 * symptom that a strict 3-day window produced when it landed on a sparse day.
 */
const INTRADAY_FETCH_DAYS_BACK = 8;

export const CHART_PERIOD_PRESETS: Record<ChartPeriod, ChartPeriodPreset> = {
  // ── Intraday (5-minute bars) — share one cache slot ──────────────────────
  // WHY visibleBars on BOTH (not a day-window): intraday sessions vary wildly
  // in bar count (a half-day holiday, a sparse dev session). A calendar-day
  // window can land on an 11-bar session and reproduce the "~10 bars" bug; a
  // bar-COUNT window via setVisibleLogicalRange always shows a fixed, dense
  // number of the most-recent candles regardless of how the sessions fell.
  //   1D ≈ last ~80 5-min bars  (~one full regular session = 78 bars)
  //   5D ≈ last ~390 5-min bars (~five sessions)
  "1D": { timeframe: "5M", fetchDaysBack: INTRADAY_FETCH_DAYS_BACK, visibleDays: 1, visibleBars: 80 },
  "5D": { timeframe: "5M", fetchDaysBack: INTRADAY_FETCH_DAYS_BACK, visibleDays: 5, visibleBars: 390 },

  // ── Daily bars — 1M / 3M / 6M / 1Y all share one cache slot ───────────────
  // Each loads the SAME daily series (one fetch) and differs ONLY in how many
  // of the most-recent bars are visible — switching is a client-side zoom.
  // visibleBars (trading-day counts) is used everywhere so the opening view is
  // a precise candle count, independent of weekend/holiday calendar gaps:
  //   1M ≈ 21 trading days, 3M ≈ 63, 6M ≈ 126, 1Y ≈ 200 (the dense default).
  "1M": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 31, visibleBars: 21 },
  "3M": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 92, visibleBars: 63 },
  "6M": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 183, visibleBars: 126 },
  // 1Y is the default view: it loads the full daily window but windows the
  // visible range to the LAST ~200 BARS so the opening view is a dense,
  // readable ~200-candle chart with the rest of the loaded history to pan into.
  "1Y": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 365, visibleBars: 200 },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * periodStartIso — ISO-8601 UTC date string for the fetch window's start.
 *
 * WHY date-only (YYYY-MM-DD): S3's OHLCV endpoint accepts date params; a
 * date-only string avoids timezone ambiguity in the query string and keeps
 * the URL stable within a calendar day (stable URL = stable HTTP cache key).
 *
 * @param period - The selected chart period.
 * @param now    - Injectable clock for tests (defaults to wall clock).
 */
export function periodStartIso(period: ChartPeriod, now: Date = new Date()): string {
  const preset = CHART_PERIOD_PRESETS[period];
  const start = new Date(now.getTime() - preset.fetchDaysBack * 24 * 60 * 60 * 1000);
  // toISOString() is always UTC; slice to date-only (first 10 chars).
  return start.toISOString().slice(0, 10);
}
