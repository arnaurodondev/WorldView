/**
 * lib/ta/timeframe-to-days.ts — maps chart timeframes to sentiment lookback windows.
 *
 * WHY THIS EXISTS (G-018 / PLAN-0091 Wave F-2):
 *   The SENTI overlay must cover the same time range visible in the OHLCV chart.
 *   Hardcoding 90 days made the overlay "die" at the left edge on timeframes wider
 *   than 3 months. This utility provides the canonical mapping so TAOverlayPanel
 *   can request the right number of days from S9.
 *
 * WHY S9 cap at 365: the sentiment-timeseries endpoint accepts days ≤ 365
 *   (FastAPI Query ge=1, le=365). Anything wider is capped.
 */

import type { Timeframe } from "@/lib/chart-adapter";

// Lookback days per timeframe — covers or slightly exceeds the visible bars so
// the overlay never appears truncated on the left edge of the chart.
const TIMEFRAME_TO_DAYS: Record<Timeframe, number> = {
  "5M": 7,    // 1 trading week
  "1H": 14,   // 2 trading weeks
  "1D": 30,   // ~1 month of daily bars
  "1W": 30,   // ~4 trading weeks
  "1M": 90,   // ~3 months
};

// S9 sentiment-timeseries endpoint max: days ≤ 365
const S9_MAX_DAYS = 365;

export function getMaxDaysForTimeframe(tf: Timeframe): number {
  return Math.min(TIMEFRAME_TO_DAYS[tf] ?? 90, S9_MAX_DAYS);
}
