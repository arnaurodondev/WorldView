/**
 * components/instrument/chart/chartPeriods.ts — period → fetch-params presets
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 2):
 * The chart toolbar exposes a PERIOD selector (1D / 5D / 1M / 3M / 6M / 1Y /
 * 5Y / MAX) like TradingView/Finviz, but the S9 price-history endpoint
 * (GET /v1/ohlcv/{id}?timeframe&start) speaks in BAR RESOLUTION ("5M", "1D",
 * "1W", "1M") + a start date. This module is the single source of truth for
 * that translation so OHLCVChart and its tests can never drift apart.
 *
 * DESIGN DECISION — share one fetch per bar resolution, zoom client-side:
 * 1M / 3M / 6M / 1Y all map to DAILY bars and share ONE fetch window (730 days).
 * Switching between them therefore:
 *   1. hits the SAME TanStack Query cache slot (qk.instruments.ohlcv(id,"1D"))
 *      → zero refetch, instant switch (requirement 5: tab/period switching
 *      must not refetch);
 *   2. only adjusts the chart's VISIBLE RANGE client-side (see OHLCVChart's
 *      visible-range effect) — lightweight-charts can re-window already-loaded
 *      bars without any network round-trip.
 * The other groups each need their own bar resolution, so they get their own
 * cache slots keyed by their timeframe:
 *   • 1D / 5D     → "5M" intraday bars (share one slot);
 *   • 5Y          → "1W" weekly bars (derived daily→weekly by S3 at query time);
 *   • MAX         → "1M" monthly bars (derived daily→monthly by S3).
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

// ── 2026-06-15 BACKEND-HONEST TIMEFRAME SET (earlier fix) ────────────────────
// The original set (1D/1W/1M/3M/1Y/5Y) advertised periods the S3 market-data
// backend CANNOT serve, which produced all three reported bugs. Verified live
// against S9 → S3 for AAPL (01900000-…-1001) on 2026-06-15:
//
//   timeframe  stored data                          period that used it
//   ─────────  ───────────────────────────────────  ───────────────────
//   5m         ~297 bars over ~1 month (intraday)    1D
//   1h         ~46 bars over ~1 month (SPARSE)       1W  ← only ~10/day
//   1d         274 bars, May-2025 → Jun-2026 (~13mo) 1M / 3M / 1Y
//   1w         0 bars (NOT stored)                   5Y  ← was always empty!
//   1M(month)  0 bars (NOT stored)                   (unused)
//
// The first remediation DROPPED 1W and 5Y entirely (no weekly/monthly bars
// existed and S9 exposed no derive path), replacing them with 5D (intraday)
// and 6M (daily).
//
// ── 2026-06-15 LONG-RANGE RESTORE (this change) ──────────────────────────────
// A sibling backend agent has now wired S3's pre-existing (but previously
// dead) derive logic — DeriveOHLCVUseCase aggregates stored DAILY bars into
// weekly ("1w") and monthly ("1M") bars on demand at QUERY TIME (no polling,
// no extra ingestion). `_DERIVABLE = {ONE_WEEK, ONE_MONTH}` in
// services/market-data/.../use_cases/derive_ohlcv.py. So weekly + monthly
// resolutions are now SERVABLE through the same /v1/ohlcv/{id}?timeframe=…
// endpoint the chart already uses.
//
// That lets us RESTORE the long horizons honestly:
//   • 5Y  → "1W" weekly bars  (≈ 260 weeks for a full 5 years).
//   • MAX → "1M" monthly bars (the deepest zoom-out; whole history available).
//
// WHY weekly for 5Y and monthly for MAX (not e.g. monthly for both): weekly
// bars give 5Y a dense, readable ~260-candle series — enough granularity to
// read multi-month swings — while monthly is the right granularity only once
// the horizon is many years (MAX), where ~260 weekly candles would be too
// noisy/crowded. Each long period gets its OWN bar resolution → its OWN
// TanStack cache slot, exactly like the intraday (1D/5D → 5M) and daily
// (1M/3M/6M/1Y → 1D) groups already do.
//
// ── HONESTY: data-depth limit (NOT a bug) ────────────────────────────────────
// The derived bars are aggregated from the stored DAILY series, which today is
// only ~13 months deep (~274 daily bars). So a 5Y-weekly view currently shows
// ~13 months of weekly bars (~57 weeks), and MAX-monthly shows ~13 monthly
// bars — i.e. "5 years available: ~1.1y" until more daily history is ingested.
// This is a DATA-DEPTH limit of the source series, not a chart defect:
//   • The chart already renders whatever range exists (the visible-range effect
//     in OHLCVChart CLAMPS the window to the first/last loaded bar, and the
//     bar-COUNT windowing via visibleBars shows min(visibleBars, bars.length)),
//     so a short weekly/monthly series fills the canvas instead of leaving a
//     broken/empty axis. The 0-bar and <2-plottable-bar empty states still
//     guard the genuinely-empty case.
//   • As the daily backfill deepens, the SAME 5Y/MAX presets automatically
//     surface more weekly/monthly bars with no frontend change — the fetch
//     windows below (1830d / 7300d) are already sized for the full horizon.
export type ChartPeriod = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";

/** Display order for the toolbar — shortest to longest, TradingView style. */
export const CHART_PERIODS: readonly ChartPeriod[] = [
  "1D",
  "5D",
  "1M",
  "3M",
  "6M",
  "1Y",
  "5Y",
  "MAX",
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

/**
 * Fetch window for the WEEKLY (5Y) period — "1W" derived bars.
 *
 * WHY 1830 (≈ 5 years + 1 day of slack): 5 years × 365 days = 1825; +5 guards
 * the boundary where "now - 1825d" lands exactly on the first available bar's
 * date and a DST/UTC rounding shaves it off (same +1-day rationale as the
 * daily window). S3 DERIVES weekly bars from whatever daily history exists
 * inside this window, so the view returns the full 5 years once the daily
 * series is that deep — and gracefully returns fewer weeks (~57 today) while
 * the daily backfill is shallower. limit=1000 (from OHLCVChart) is the ceiling;
 * 5 years is ~260 weekly bars, well under it.
 */
const WEEKLY_FETCH_DAYS_BACK = 1830;

/**
 * Fetch window for the MONTHLY (MAX) period — "1M" derived bars.
 *
 * WHY 7300 (≈ 20 years): MAX means "all available history". The daily source
 * series will never realistically exceed ~20 years for these instruments, so a
 * 20-year window guarantees we ask for everything; S3 derives monthly bars from
 * however much daily history actually exists and returns only that (~13 monthly
 * bars today). 20 years is ~240 monthly bars — still under the limit=1000 cap.
 * WHY not "no start at all": S9 injects only a 90-day default start when the
 * caller omits one (see api-gateway market route), which would silently clamp
 * MAX to one quarter — so we MUST pass an explicit, very-wide start.
 */
const MONTHLY_FETCH_DAYS_BACK = 7300;

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

  // ── Weekly bars — 5Y stands alone in its own cache slot ───────────────────
  // 5Y maps to the DERIVED "1W" resolution (S3 aggregates daily→weekly at query
  // time). visibleBars=260 ≈ the number of weeks in 5 years, so the opening
  // view shows the whole horizon when the daily backfill is deep enough. When
  // it's shallow (~57 weeks today) the chart clamps to the available bars
  // (Math.min in OHLCVChart's windowing effect) and fills the canvas — a data-
  // depth limit, not a broken axis. fetchDaysBack ≫ visibleDays so client-side
  // zoom-out within the weekly series never needs a refetch.
  "5Y": { timeframe: "1W", fetchDaysBack: WEEKLY_FETCH_DAYS_BACK, visibleDays: 1830, visibleBars: 260 },

  // ── Monthly bars — MAX stands alone in its own cache slot ─────────────────
  // MAX maps to the DERIVED "1M" resolution (S3 aggregates daily→monthly). This
  // is the deepest zoom-out: visibleBars=240 ≈ 20 years of months, so the view
  // shows ALL available monthly bars (today ~13; more as the daily series
  // grows). Same graceful-clamp behaviour as 5Y for the shallow-history case.
  // NOTE: "1M" is the frontend's UPPERCASE month convention; the gateway
  // normalizer (lib/api/instruments.ts) preserves "1M" as-is because S3's
  // Timeframe.ONE_MONTH is case-sensitive "1M" — lowercase "1m" would be
  // rejected as an intraday minute resolution.
  "MAX": { timeframe: "1M", fetchDaysBack: MONTHLY_FETCH_DAYS_BACK, visibleDays: 7300, visibleBars: 240 },
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
