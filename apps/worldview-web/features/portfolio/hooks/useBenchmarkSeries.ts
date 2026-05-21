/**
 * useBenchmarkSeries — fetches SPY OHLCV for the active performance period.
 *
 * WHY THIS EXISTS: PerformanceChartPanel overlays a SPY benchmark series on the
 * portfolio line. DISCUSS-10 locked benchmark=SPY-only for v1. staleTime=30s
 * because intraday data for SPY updates every 30s during market hours.
 * DATA SOURCE: GET /v1/ohlcv/SPY?timeframe=1d&limit=N (single-instrument OHLCV)
 * DESIGN REFERENCE: PRD-0089 W2 §4.18, DISCUSS-10
 *
 */
"use client";
// WHY "use client": useQuery (TanStack) requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import type { PerfPeriod } from "@/components/portfolio/PerformanceChartPanel";

// Map display period to approximate calendar-day lookback for OHLCV start param.
// WHY calendar days (not trading days): getOHLCV accepts start= ISO date;
// extra days are filtered server-side and are cheaper than a missing week.
const PERIOD_DAYS: Record<PerfPeriod, number> = {
  "1W": 10,
  "1M": 35,
  "3M": 95,
  "6M": 185,
  "1Y": 375,
  "All": 3000,
};

interface UseBenchmarkSeriesResult {
  data: number[] | null;
  isLoading: boolean;
  isError: boolean;
}

// WHY string constant: instrument lookup uses the ticker string directly in
// the OHLCV endpoint path (S9 resolves SPY → instrument_id internally).
const SPY_TICKER = "SPY";

export function useBenchmarkSeries(period: PerfPeriod): UseBenchmarkSeriesResult {
  const { accessToken } = useAuth();
  const days = PERIOD_DAYS[period];
  // Compute start date as ISO YYYY-MM-DD string so getOHLCV can filter server-side.
  const startDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);

  const { data, isLoading, isError } = useQuery({
    // WHY qk.market.benchmarkSeries: keeps the benchmark series separate from
    // instrument-detail OHLCV keys so invalidations don't cross-contaminate.
    // Added to lib/query/keys.ts in step 4.23 (PRD-0089 W2 §4.23).
    // WHY startDate in key: the queryFn uses startDate to filter OHLCV bars.
    // Without it, the cache key is identical across the date boundary (midnight UTC)
    // and the cache serves yesterday's bars with today's request (F-DATA-001, QA 2026-05-21).
    queryKey: qk.market.benchmarkSeries(SPY_TICKER, period, startDate),
    queryFn: async () => {
      // WHY single-instrument call not batch: SPY is always the only benchmark (v1).
      // Batch overhead (POST + body parsing) would be wasteful for one ticker.
      const gw = createGateway(accessToken);
      // WHY getOHLCV with timeframe "1D": daily bars give clean multi-week trends;
      // intraday bars would produce thousands of data points for "All" period.
      const result = await gw.getOHLCV(SPY_TICKER, { timeframe: "1D", start: startDate });
      return result.bars.map((b) => b.close);
    },
    enabled: !!accessToken,
    staleTime: 30_000, // 30s — SPY updates during market hours
  });

  return { data: data ?? null, isLoading, isError };
}
