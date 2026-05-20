// lib/technicals.ts — Client-side technical indicator computation from OHLCV bars.
// WHY THIS EXISTS: RSI/ATR are not returned by any S9 endpoint; the detail page
//   already fetches 1D OHLCV for the chart so we reuse those bars client-side.
// WHO USES IT: components/instrument/quote/TechnicalsCard.tsx via useMetricsTableData.
// DATA SOURCE: GET /v1/instruments/{id}/ohlcv?timeframe=1D.
// DESIGN REFERENCE: spec 0088 §6.7.2, plan 0090 T-A-01.
import type { OHLCVBar } from "@/types/api";

// computeRSI — 14-period Wilder Relative Strength Index for the LAST bar.
// Returns null when fewer than period+1 bars exist (not enough deltas).
export function computeRSI(bars: OHLCVBar[], period = 14): number | null {
  if (bars.length < period + 1) return null;
  let avgGain = 0;
  let avgLoss = 0;
  // Seed averages from the first `period` deltas (simple mean — Wilder's seed).
  for (let i = 1; i <= period; i++) {
    const delta = bars[i].close - bars[i - 1].close;
    if (delta >= 0) avgGain += delta;
    else avgLoss += -delta;
  }
  avgGain /= period;
  avgLoss /= period;
  // Wilder smoothing: each new bar updates the running average by a factor of 1/period.
  // This is mathematically a recursive EMA with alpha = 1/period (NOT simple mean).
  for (let i = period + 1; i < bars.length; i++) {
    const delta = bars[i].close - bars[i - 1].close;
    const gain = delta > 0 ? delta : 0;
    const loss = delta < 0 ? -delta : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
  }
  // Div-by-zero guard: zero average loss means the series has only gains (or flat),
  // by Wilder convention RSI saturates at 100 in that case.
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

// computeATR — 14-period Wilder Average True Range for the LAST bar.
// Returns null when fewer than period+1 bars exist (no prevClose for first TR).
export function computeATR(bars: OHLCVBar[], period = 14): number | null {
  if (bars.length < period + 1) return null;
  const tr = (i: number): number => {
    const hl = bars[i].high - bars[i].low;
    const hc = Math.abs(bars[i].high - bars[i - 1].close);
    const lc = Math.abs(bars[i].low - bars[i - 1].close);
    return Math.max(hl, hc, lc);
  };
  // Seed ATR with the simple mean of the first `period` true ranges.
  let atr = 0;
  for (let i = 1; i <= period; i++) atr += tr(i);
  atr /= period;
  // Wilder smoothing identical to RSI: alpha = 1/period recursive update.
  for (let i = period + 1; i < bars.length; i++) {
    atr = (atr * (period - 1) + tr(i)) / period;
  }
  return atr;
}
