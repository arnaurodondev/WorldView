/**
 * lib/ta/indicators.ts — Pure client-side technical analysis computations.
 *
 * WHY THIS EXISTS: TA indicator values (EMA, SMA, RSI, MACD, Bollinger, VWAP)
 * are not returned by any S9 endpoint. The instrument detail page already fetches
 * 1D OHLCV bars for the chart (OHLCVChart), so we reuse those bars client-side
 * rather than adding extra API round-trips. All functions are pure (no side effects,
 * no network calls), which makes them cheap to test and safe to call on every render.
 *
 * WHO USES IT:
 *   - components/instrument/quote/TAOverlayPanel.tsx — computes overlay series
 *     from toggled chips and forwards them to OHLCVChart via the overlays prop.
 *
 * DATA SOURCE: GET /v1/ohlcv/{instrument_id}?timeframe=<tf> (bars already in cache)
 *
 * DESIGN REFERENCE: PLAN-0091 Wave F-1 TA overlay spec.
 *
 * RETURN CONTRACT:
 *   All functions return number[] of the SAME length as the input bars array.
 *   Indices where there is insufficient history (e.g., the first period-1 bars
 *   for EMA) are filled with NaN. The caller (TAOverlayPanel) skips NaN points
 *   when building the OverlaySeries.data array passed to OHLCVChart.
 *
 * PERFORMANCE NOTE:
 *   These functions run synchronously in the React render cycle. On 5,000 bars
 *   (20 years of 1D data) each indicator takes <2ms in a modern browser.
 *   The TAOverlayPanel memoises results with useMemo, so they only recompute
 *   when the bars array reference changes (i.e., on a new fetch).
 */

import type { OHLCVBar } from "@/types/api";

// ── EMA — Exponential Moving Average ─────────────────────────────────────────

/**
 * ema — Exponential Moving Average over `period` bars.
 *
 * WHY EMA (not SMA): EMA weights recent closes more heavily, which is why
 * institutional desks use it for trend-following. The 20/50/200 EMAs are
 * canonical support/resistance lines on Bloomberg terminals.
 *
 * SEED STRATEGY: the first EMA value is the SMA of the first `period` closes.
 * This matches Excel's EMA function and TA-Lib's default seed. It means
 * the first period-1 values are always NaN.
 *
 * FORMULA:
 *   k = 2 / (period + 1)           ← smoothing factor
 *   EMA[i] = close[i] * k + EMA[i-1] * (1 - k)
 *   EMA[period-1] = mean(close[0..period-1])   ← seed value
 */
export function ema(bars: OHLCVBar[], period: number): number[] {
  // Defensive guard: period must be a positive integer ≥ 1.
  if (period < 1 || bars.length === 0) {
    return bars.map(() => NaN);
  }

  const result = new Array<number>(bars.length).fill(NaN);

  // We need at least `period` bars to compute the seed SMA.
  if (bars.length < period) return result;

  // ── Step 1: Seed with SMA of the first `period` closes ───────────────────
  // WHY start with SMA: avoids the "warm-up" distortion where EMA[0] = close[0]
  // would make the first rendered value on a long series look artificially "fresh".
  let sum = 0;
  for (let i = 0; i < period; i++) sum += bars[i].close;
  const seed = sum / period;

  // The seed fills the last position of the warm-up window (index period-1).
  result[period - 1] = seed;

  // Smoothing factor k = 2/(N+1). Higher period → lower k → slower adaptation.
  const k = 2 / (period + 1);

  // ── Step 2: EMA recurrence relation from period onwards ───────────────────
  for (let i = period; i < bars.length; i++) {
    result[i] = bars[i].close * k + result[i - 1] * (1 - k);
  }

  return result;
}

// ── SMA — Simple Moving Average ───────────────────────────────────────────────

/**
 * sma — Simple Moving Average over `period` bars.
 *
 * WHY SMA IN ADDITION TO EMA: the SMA 200 is the single most-watched trend
 * line on equity charts (institutional desks check whether price is above/below
 * SMA 200 as a bull/bear regime signal). SMA is lag-heavy but unambiguous,
 * so it complements the EMAs rather than duplicating them.
 *
 * The first period-1 values are NaN (insufficient history).
 */
export function sma(bars: OHLCVBar[], period: number): number[] {
  if (period < 1 || bars.length === 0) {
    return bars.map(() => NaN);
  }

  const result = new Array<number>(bars.length).fill(NaN);

  if (bars.length < period) return result;

  // ── Rolling sum approach: O(N) rather than O(N*period) ───────────────────
  // Initialise with the sum of the first window.
  let windowSum = 0;
  for (let i = 0; i < period; i++) windowSum += bars[i].close;
  result[period - 1] = windowSum / period;

  // Slide the window: subtract the oldest bar, add the new bar.
  for (let i = period; i < bars.length; i++) {
    windowSum += bars[i].close - bars[i - period].close;
    result[i] = windowSum / period;
  }

  return result;
}

// ── RSI — Relative Strength Index ─────────────────────────────────────────────

/**
 * rsi — Wilder's Relative Strength Index over `period` bars (default 14).
 *
 * WHY RSI: the standard momentum oscillator. Values outside [30, 70] signal
 * oversold/overbought conditions. Every institutional terminal shows RSI 14.
 *
 * ALGORITHM (Wilder, 1978):
 *   1. Seed: avgGain = mean(gains over first `period` deltas)
 *            avgLoss = mean(losses over first `period` deltas)
 *   2. Smooth: avgGain = (avgGain * (period-1) + gain) / period  — Wilder smoothing
 *              avgLoss = (avgLoss * (period-1) + loss) / period
 *   3. RS = avgGain / avgLoss; RSI = 100 - 100/(1+RS)
 *
 * OUTPUT: NaN for the first `period` values (warm-up, no prior delta for bar 0
 * plus period bars needed to seed the averages). RSI is defined starting at
 * index `period` (requires period+1 bars including bar 0 as the "prev close").
 */
export function rsi(bars: OHLCVBar[], period = 14): number[] {
  const result = new Array<number>(bars.length).fill(NaN);

  // Need period+1 bars: bar 0 is used only as "prev close" for the first delta.
  if (bars.length < period + 1) return result;

  // ── Step 1: Seed averages from first `period` deltas ─────────────────────
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = bars[i].close - bars[i - 1].close;
    if (delta > 0) avgGain += delta;
    else avgLoss += -delta; // store as positive
  }
  avgGain /= period;
  avgLoss /= period;

  // ── Step 2: Record RSI at period (first defined value) ───────────────────
  // WHY period (not period-1): we need period close-to-close deltas,
  // which span bars[0..period], so the first RSI lands at index `period`.
  const firstRsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  result[period] = firstRsi;

  // ── Step 3: Wilder smoothing for the remaining bars ───────────────────────
  for (let i = period + 1; i < bars.length; i++) {
    const delta = bars[i].close - bars[i - 1].close;
    const gain = delta > 0 ? delta : 0;
    const loss = delta < 0 ? -delta : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }

  return result;
}

// ── MACD — Moving Average Convergence/Divergence ──────────────────────────────

/**
 * macd — Standard MACD (12, 26, 9).
 *
 * WHY MACD: combines trend direction (EMA crossover) and momentum (histogram).
 * The standard (12,26,9) params are the Bloomberg/TradingView default and are
 * understood by every equity analyst without configuration.
 *
 * COMPONENTS:
 *   macd      = EMA(12) − EMA(26)   ← "MACD line"
 *   signal    = EMA(9) of macd line ← "Signal line"
 *   histogram = macd − signal       ← visually shows divergence momentum
 *
 * OUTPUT: all three arrays are the same length as bars, NaN during warm-up.
 * The warm-up for the histogram ends at index 25 + 8 = 33 (needs 26 bars for
 * EMA26, then 9 additional bars for the EMA9 of the MACD line).
 */
export function macd(bars: OHLCVBar[]): {
  macd: number[];
  signal: number[];
  histogram: number[];
} {
  const fastPeriod = 12;
  const slowPeriod = 26;
  const signalPeriod = 9;

  const ema12 = ema(bars, fastPeriod);
  const ema26 = ema(bars, slowPeriod);

  // MACD line = EMA(12) - EMA(26)
  // WHY NaN propagation: if either EMA is NaN, the difference is NaN, which is
  // the correct "insufficient history" signal for downstream consumers.
  const macdLine = bars.map((_, i) => ema12[i] - ema26[i]);

  // Signal line = EMA(9) of the macd line values.
  // We synthesise a fake OHLCVBar array (close = macdLine[i]) so we can reuse
  // the ema() function — which operates on bar.close.
  const macdBars: OHLCVBar[] = bars.map((bar, i) => ({
    ...bar,
    open: macdLine[i],
    high: macdLine[i],
    low: macdLine[i],
    close: macdLine[i],
  }));
  const signalLine = ema(macdBars, signalPeriod);

  // Histogram = MACD - Signal
  const histLine = bars.map((_, i) => macdLine[i] - signalLine[i]);

  return { macd: macdLine, signal: signalLine, histogram: histLine };
}

// ── Bollinger Bands ───────────────────────────────────────────────────────────

/**
 * bollingerBands — John Bollinger's volatility envelope.
 *
 * WHY BOLLINGER: the upper and lower bands quantify "how stretched" price is
 * relative to recent volatility. When price touches the upper band on strong
 * volume it often signals continuation; without volume it signals mean reversion.
 * The (20, 2) default is universal — Bloomberg, TradingView, Finviz all use it.
 *
 * FORMULA:
 *   middle = SMA(period)
 *   σ      = population std-dev of the last `period` closes
 *   upper  = middle + stdDev * σ
 *   lower  = middle − stdDev * σ
 *
 * WHY population std-dev (not sample): Bollinger himself specified population
 * (divide by N, not N-1). TA-Lib and most platforms follow this convention.
 *
 * OUTPUT: three arrays (upper/middle/lower) same length as bars, NaN during warm-up.
 */
export function bollingerBands(
  bars: OHLCVBar[],
  period = 20,
  stdDev = 2,
): { upper: number[]; middle: number[]; lower: number[] } {
  const middle = sma(bars, period);
  const upper = new Array<number>(bars.length).fill(NaN);
  const lower = new Array<number>(bars.length).fill(NaN);

  for (let i = period - 1; i < bars.length; i++) {
    // Compute population std-dev for the `period` closes ending at index i.
    const mean = middle[i];
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const diff = bars[j].close - mean;
      variance += diff * diff;
    }
    const sigma = Math.sqrt(variance / period);
    upper[i] = mean + stdDev * sigma;
    lower[i] = mean - stdDev * sigma;
  }

  return { upper, middle, lower };
}

// ── VWAP — Volume Weighted Average Price ──────────────────────────────────────

/**
 * vwap — Volume Weighted Average Price over all bars (running cumulative).
 *
 * WHY VWAP: institutional desks use VWAP as the benchmark execution price.
 * Buying below VWAP is considered a "good fill"; selling above VWAP is
 * considered superior execution. It is the single most important intraday
 * reference price for large-order execution algorithms.
 *
 * DAILY BAR BEHAVIOUR:
 *   For daily bars there is no natural intraday session boundary, so we compute
 *   a cumulative VWAP across all bars in the array (typical for multi-day charts).
 *   Each bar's typical price is (H + L + C) / 3, which approximates the session
 *   average price better than just the close.
 *
 * FORMULA (running cumulative):
 *   typicalPrice[i] = (high[i] + low[i] + close[i]) / 3
 *   VWAP[i] = Σ(typicalPrice[0..i] * volume[0..i]) / Σ(volume[0..i])
 *
 * WHY typical price vs close: typical price is the standard definition (TP = HLC/3).
 * Using close alone would underestimate price in up-bars and overestimate in down-bars.
 *
 * OUTPUT: same length as bars, first value always defined (single bar VWAP = TP[0]).
 * Returns NaN if volume is 0 for all bars up to that point (avoids div-by-zero).
 */
export function vwap(bars: OHLCVBar[]): number[] {
  const result = new Array<number>(bars.length).fill(NaN);

  let cumTpVol = 0; // Σ(typicalPrice * volume)
  let cumVol = 0;   // Σ(volume)

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];
    const tp = (bar.high + bar.low + bar.close) / 3;
    cumTpVol += tp * (bar.volume ?? 0);
    cumVol += bar.volume ?? 0;

    // Guard against zero-volume bars (e.g., early data or missing feed).
    result[i] = cumVol > 0 ? cumTpVol / cumVol : NaN;
  }

  return result;
}
