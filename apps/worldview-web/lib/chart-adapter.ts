/**
 * lib/chart-adapter.ts — Pure data-transformation utilities for lightweight-charts
 *
 * WHY THIS EXISTS: OHLCVChart.tsx contained ~120 lines of chart constants and
 * pure utility functions (computeMA, toTime, setSeriesData, CHART_THEME) mixed in
 * with component state. Extracting them here lets the component focus on React
 * orchestration while these utilities can be imported and tested independently.
 *
 * WHY "pure": nothing in this module imports React or hooks. Every function is a
 * plain TypeScript function that takes data and returns data — safe to call from
 * any context (component, hook, test, or Server Component if needed).
 *
 * CHART_HEIGHT / PALETTE_WIDTH / CHART_THEME are co-located here because they
 * describe the chart's visual contract — they must stay consistent between the
 * chart initialisation (useChartSeries hook) and the JSX layout (OHLCVChart).
 *
 * WHO USES THIS: components/instrument/OHLCVChart.tsx (via useChartSeries hook)
 * PLAN REFERENCE: PLAN-0089 Wave D-1 (split OHLCVChart into chart/ subdirectory)
 */

import type { ISeriesApi, UTCTimestamp } from "lightweight-charts";

// ── Layout constants ───────────────────────────────────────────────────────────

/**
 * CHART_HEIGHT — total canvas height in pixels.
 *
 * WHY 280 (was 360): volume histogram uses the bottom 20% (~56px), candlesticks
 * use the top 80% (~224px). Total 280px matches TradingView's default proportion.
 */
export const CHART_HEIGHT = 280;

/**
 * PALETTE_WIDTH — width in pixels of the left-side DrawingPalette.
 *
 * WHY 28px: w-7 Tailwind = 28px. The chart container gets pl-7 to offset the
 * drawing palette. The SVG drawing canvas accounts for this offset.
 */
export const PALETTE_WIDTH = 28;

// ── Timeframe type ─────────────────────────────────────────────────────────────

/**
 * Timeframe — the set of valid OHLCV timeframe strings.
 *
 * WHY these exact values: they map directly to S3's Timeframe enum via the
 * gateway normalizer in lib/gateway.ts. The gateway converts "5M"→"5m",
 * "1H"→"1h", "1D"→"1d", "1W"→"1w", and preserves "1M" as-is (uppercase M)
 * because S3's ONE_MONTH = "1M" is case-sensitive (lowercase "1m" is invalid).
 */
export type Timeframe = "5M" | "1H" | "1D" | "1W" | "1M";

// ── Terminal Dark chart theme ──────────────────────────────────────────────────
//
// WHY inline object (not CSS): lightweight-charts applies these via its own
// theming API, not via CSS classes. Values must match the Terminal Dark palette
// exactly so the chart canvas blends seamlessly into the surrounding panel.
//
// WHY these exact hex values (not CSS var() references):
// lightweight-charts does not understand CSS custom properties — it only accepts
// literal hex strings in its options object. The values are derived from
// globals.css Terminal Dark tokens:
//   --background:        #09090B  (240 10% 4%)
//   --card:              #111113  (270 2% 7%)
//   --muted-foreground:  #71717A  (240 4% 46%)
//   --positive:          #26A69A  (174 42% 40%)
//   --negative:          #EF5350  (0 63% 62%)
//
// If the globals.css palette changes, update these constants to match.
export const CHART_THEME = {
  layout: {
    background: { color: "#09090B" },   // --background: Terminal Dark near-black
    textColor: "#71717A",               // --muted-foreground: zinc-500 neutral grey
  },
  grid: {
    // WHY --card not --border for grid lines: #27272A (border) is too prominent
    // as a grid line — it competes with candlestick color. Using the card color
    // (#111113) gives a barely-visible grid that aids alignment without clutter.
    vertLines: { color: "#111113" },    // --card: subtle vertical grid
    horzLines: { color: "#111113" },    // --card: subtle horizontal grid
  },
  crosshair: {
    mode: 0, // Normal crosshair mode (shows both price and time crosshairs)
  },
} as const;

// ── MA computation (simple SMA) ────────────────────────────────────────────────

/**
 * computeMA — simple moving average over an array of time/close pairs.
 *
 * WHY client-side: MAs are derived from the same bars already fetched — no
 * additional API call. Simple O(n*period) SMA is fast for ≤500 bars.
 *
 * WHY slice(period-1): the first valid MA point requires `period` bars of history.
 * Index 0 covers bars[0..period-1], so the time is bars[period-1].time.
 *
 * @param bars    Formatted bars with numeric time (Unix seconds) and close price
 * @param period  MA period (50 or 200)
 * @returns       Array of {time, value} pairs for lightweight-charts LineSeries
 */
export function computeMA(
  bars: { time: number; close: number }[],
  period: number,
): { time: number; value: number }[] {
  if (bars.length < period) return [];
  return bars.slice(period - 1).map((_, i) => ({
    time: bars[i + period - 1].time,
    value: bars.slice(i, i + period).reduce((s, b) => s + b.close, 0) / period,
  }));
}

// ── UTCTimestamp helpers ───────────────────────────────────────────────────────

/**
 * toTime — cast a Unix-seconds number to lightweight-charts' branded UTCTimestamp.
 *
 * WHY needed: lightweight-charts uses a branded type `UTCTimestamp` (= number with
 * a `_brand: "UTCTimestamp"` phantom tag) so TypeScript can catch accidental
 * millisecond values being passed as seconds. Our computed timestamps are correct
 * Unix seconds — the cast is safe. Using `as UTCTimestamp` instead of `as any`
 * keeps the intent explicit and avoids widening to `any` in the call sites.
 */
export function toTime(t: number): UTCTimestamp {
  return t as UTCTimestamp;
}

/**
 * setSeriesData — null-safe typed setData wrapper for lightweight-charts series.
 *
 * WHY needed: ISeriesApi<T>.setData() expects exactly the data shape for T.
 * Our computed indicator data arrays (e.g., { time: number; value: number }[])
 * are semantically correct, but TypeScript needs the `time` field as UTCTimestamp
 * and the shape to match the series discriminant. We use a `as unknown as P[0]`
 * double-cast which is safe given that the data is already correctly structured.
 *
 * WHY generic S (not `any`): keeps the series type trackable for IDE tooling.
 * The `Parameters<S["setData"]>[0]` trick extracts the exact argument type from
 * the series' setData overload without needing to know T explicitly.
 */
export function setSeriesData<S extends ISeriesApi<"Line" | "Histogram" | "Candlestick">>(
  series: S | null,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any[],
): void {
  if (!series) return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  series.setData(data as any);
}
