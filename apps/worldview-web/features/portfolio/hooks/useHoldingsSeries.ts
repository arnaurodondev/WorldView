/**
 * useHoldingsSeries — batch-fetches 14-day daily OHLCV for all holdings.
 *
 * WHY THIS EXISTS: SparklineCellRenderer needs 14 close-price data points per
 * ticker to render the trend sparkline. Fetching per-ticker would mean N round-
 * trips (one per holding); the batch endpoint caps that at one. staleTime=15min
 * because 14-day daily bars don't change faster than that (the last bar closes at
 * EOD). This matches the watchlist sparkline pattern but with 1d bars + limit=14
 * (not 5m×78 which would be intraday noise).
 * DATA SOURCE: POST /v1/ohlcv/batch (via getBatchOhlcvBars)
 * DESIGN REFERENCE: PRD-0089 W2 §4.17, C-36
 */
"use client";
// WHY "use client": useQuery (TanStack) requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import type { Holding } from "@/types/api";

interface UseHoldingsSeriesResult {
  /** Record<ticker, close-prices[]> — SparklineCellRenderer consumes this keyed by ticker */
  holdingsSeries: Record<string, number[]>;
  isLoading: boolean;
}

export function useHoldingsSeries(holdings: Holding[]): UseHoldingsSeriesResult {
  const { accessToken } = useAuth();

  // Build two parallel arrays: tickers (for query key) + instrument_ids (for the API call)
  // WHY filter falsy: holdings that haven't resolved a ticker yet should not
  // pollute the batch request or the query key with empty strings.
  const tickers = holdings.map((h) => h.ticker).filter(Boolean) as string[];
  const instrumentIds = holdings.map((h) => h.instrument_id).filter(Boolean) as string[];

  const { data, isLoading } = useQuery({
    // WHY instrumentIds (not tickers) in the cache key: tickers are derived from
    // company-overview enrichment which resolves incrementally. Using tickers
    // causes unnecessary query refires as each holding's ticker resolves.
    // instrumentIds are immutable (set at holding creation) so the key is stable
    // from the first render (F-DS-002, QA 2026-05-21).
    queryKey: qk.instruments.ohlcvBatch(instrumentIds, "1d", 14),
    queryFn: () =>
      createGateway(accessToken).getBatchOhlcvBars({
        instrument_ids: instrumentIds,
        timeframe: "1d",
        limit: 14,
      }),
    enabled: instrumentIds.length > 0 && !!accessToken,
    staleTime: 15 * 60_000, // 15 min — daily bars don't change intraday
  });

  // Build a ticker-keyed map so SparklineCellRenderer can look up by ticker in O(1)
  const holdingsSeries: Record<string, number[]> = {};
  if (data) {
    for (const result of data.results) {
      // Find the holding whose instrument_id matches this result
      const holding = holdings.find((h) => h.instrument_id === result.instrument_id);
      if (holding?.ticker) {
        holdingsSeries[holding.ticker] = result.bars.map((b) => b.close);
      }
    }
  }

  return { holdingsSeries, isLoading };
}
