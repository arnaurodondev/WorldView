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

export type ChartPeriod = "1D" | "1W" | "1M" | "3M" | "1Y" | "5Y";

/** Display order for the toolbar — shortest to longest, TradingView style. */
export const CHART_PERIODS: readonly ChartPeriod[] = [
  "1D",
  "1W",
  "1M",
  "3M",
  "1Y",
  "5Y",
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

/** The period the chart opens on — daily bars, ~200 visible of ~500 loaded. */
export const DEFAULT_CHART_PERIOD: ChartPeriod = "1Y";

/** Shared fetch window for every daily-bar period (≈ 500 trading days). */
const DAILY_FETCH_DAYS_BACK = 730;

export const CHART_PERIOD_PRESETS: Record<ChartPeriod, ChartPeriodPreset> = {
  "1D": { timeframe: "5M", fetchDaysBack: 3, visibleDays: 1 },
  "1W": { timeframe: "1H", fetchDaysBack: 8, visibleDays: 7 },
  "1M": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 31 },
  "3M": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 92 },
  // 1Y is the default view: it loads the full ~500-bar daily window but windows
  // the visible range to the LAST ~200 BARS (not 365 days) so the opening view
  // is a dense, readable ~200-candle chart with ~300 bars of loaded history to
  // pan back through. visibleBars (bar-count) overrides visibleDays here.
  "1Y": { timeframe: "1D", fetchDaysBack: DAILY_FETCH_DAYS_BACK, visibleDays: 365, visibleBars: 200 },
  "5Y": { timeframe: "1W", fetchDaysBack: 1830, visibleDays: 1827 },
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
