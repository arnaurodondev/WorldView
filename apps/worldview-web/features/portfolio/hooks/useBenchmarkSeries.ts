/**
 * features/portfolio/hooks/useBenchmarkSeries.ts — daily benchmark closes
 * (SPY / QQQ) for the analytics TWR overlay + client risk metrics.
 *
 * WHY THIS EXISTS (R2 enhancement sprint): two consumers need the SAME
 * benchmark close series for the SAME window:
 *   1. AnalyticsTwrChart — draws the normalized SPY/QQQ overlay lines.
 *   2. AnalyticsRiskMetricsPanel — computes beta vs SPY client-side.
 * Centralizing the two-step fetch (ticker → instrument_id resolve, then
 * OHLCV bars) in one hook with STABLE query keys means both consumers hit
 * the same TanStack cache entries — one network round-trip, two readers.
 *
 * FETCH CHAIN:
 *   POST /v1/instruments/resolve-tickers  (24h staleTime — IDs never change)
 *     → GET /v1/ohlcv/{id}?timeframe=1d&start={from}  per requested ticker
 *
 * WHY resolve at runtime (not hardcoded UUIDs): instrument_ids are
 * environment-specific (dev seed vs prod) — same rationale as
 * PerformanceChartPanel's SPY resolve.
 *
 * WHO USES IT: AnalyticsTab (passes the result down to chart + risk panel).
 */

"use client";

import { useQuery, useQueries } from "@tanstack/react-query";

import { useApiClient } from "@/lib/api-client";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UseBenchmarkSeriesArgs {
  /** Tickers to fetch (e.g. ["SPY", "QQQ"]). Order-insensitive. */
  tickers: string[];
  /**
   * Window start "YYYY-MM-DD". undefined = full available history (the
   * "ALL" period). Included in the OHLCV query key so each period has its
   * own cache entry.
   */
  fromDate?: string;
  /** Master gate — false disables every query (e.g. no benchmark toggled). */
  enabled: boolean;
}

export interface BenchmarkSeriesResult {
  /**
   * ticker → ascending-by-date daily closes. A ticker is ABSENT (undefined)
   * while loading, on error, or when it could not be resolved — consumers
   * render the overlay/beta only when data genuinely exists (never fake).
   */
  closesByTicker: Record<string, DatedValue[]>;
  /** True while any requested ticker is resolving/fetching. */
  isLoading: boolean;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useBenchmarkSeries({
  tickers,
  fromDate,
  enabled,
}: UseBenchmarkSeriesArgs): BenchmarkSeriesResult {
  const apiClient = useApiClient();

  // Sort for a stable query key — ["SPY","QQQ"] and ["QQQ","SPY"] must hit
  // the same cache entry (the resolve response covers both regardless).
  const sortedTickers = [...tickers].sort();

  // ── Step 1: ticker → instrument_id (one batch round-trip) ────────────────
  const { data: idMap, isLoading: resolveLoading } = useQuery({
    queryKey: ["benchmark-resolve-batch", sortedTickers],
    queryFn: () => apiClient.resolveTickersBatch(sortedTickers),
    // WHY 24h: an instrument_id never changes within a session; refetching
    // it more often is pure waste (same staleTime as PerformanceChartPanel).
    staleTime: 24 * 60 * 60 * 1000,
    enabled: enabled && sortedTickers.length > 0,
    retry: false,
  });

  // ── Step 2: daily OHLCV per resolved ticker ──────────────────────────────
  // WHY useQueries (not one combined fetch): each ticker gets its own cache
  // entry keyed by (ticker, fromDate), so toggling QQQ on doesn't refetch
  // SPY, and switching periods only refetches the changed window.
  const ohlcvResults = useQueries({
    queries: sortedTickers.map((ticker) => {
      const instrumentId = idMap?.[ticker] ?? null;
      return {
        // fromDate ?? "ALL" — undefined must still produce a distinct,
        // stable key segment (undefined inside a key array is dropped by
        // TanStack's hashing, which would collide "ALL" with any period).
        queryKey: ["benchmark-ohlcv", ticker, instrumentId, fromDate ?? "ALL"],
        queryFn: () =>
          apiClient.getOHLCV(instrumentId!, {
            timeframe: "1D",
            ...(fromDate ? { start: fromDate } : {}),
          }),
        // Only fire once the resolve produced a real instrument_id.
        enabled: enabled && Boolean(instrumentId),
        // 5 min — daily bars only change once per day; matches the
        // PerformanceChartPanel SPY overlay staleTime.
        staleTime: 5 * 60 * 1000,
        retry: false,
      };
    }),
  });

  // ── Assemble ticker → DatedValue[] map ───────────────────────────────────
  const closesByTicker: Record<string, DatedValue[]> = {};
  sortedTickers.forEach((ticker, i) => {
    const bars = ohlcvResults[i]?.data?.bars;
    if (bars && bars.length > 0) {
      closesByTicker[ticker] = bars
        .map((b) => ({
          // S3 bar timestamps are "YYYY-MM-DD" (bar_date) — slice defends
          // against a full ISO datetime ever appearing so date-string
          // comparisons in alignBenchmarkToDates stay valid.
          date: b.timestamp.slice(0, 10),
          value: b.close,
        }))
        // Ascending by date — alignBenchmarkToDates requires sorted input.
        // ISO date strings sort lexicographically = chronologically.
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    }
  });

  return {
    closesByTicker,
    isLoading:
      enabled &&
      (resolveLoading || ohlcvResults.some((r) => r.isLoading && r.fetchStatus !== "idle")),
  };
}
