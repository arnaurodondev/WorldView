/**
 * useChartTechnicals.ts
 * WHY THIS EXISTS: RSI/ATR aren't exposed by S9. The detail page already
 *   fetches 1D OHLCV for the chart, so we derive these indicators client-side
 *   from the same bars — no extra network, no second cache entry.
 * WHO USES IT: FinancialsTab (RSI/ATR row in the Technicals card). Caller
 *   reads bars from qk.instruments.ohlcv(id, "1D") via useQuery({enabled:false}).
 * DATA SOURCE: none (pure computation from OHLCVBar[]).
 * DESIGN REFERENCE: PRD-0088 §6.7.2 / §6.8, PLAN-0090 T-A-03.
 */

"use client";

import { useMemo } from "react";
import { computeRSI, computeATR } from "@/lib/technicals";
import type { OHLCVBar } from "@/types/api";

export interface ChartTechnicals {
  rsi: number | null;
  atr: number | null;
}

// WHY useMemo on [bars]: each compute walks the array (≤500 ops); memoising
// on the bars reference means recomputation only when TanStack Query updates
// the cached bars array — not on every parent render.
// WHY (bars ?? []): bars are undefined before the OHLCV query resolves;
// computeRSI/ATR both return null on insufficient data so consumers show "—".
export function useChartTechnicals(bars: OHLCVBar[] | undefined): ChartTechnicals {
  return useMemo<ChartTechnicals>(
    () => ({ rsi: computeRSI(bars ?? []), atr: computeATR(bars ?? []) }),
    [bars],
  );
}
