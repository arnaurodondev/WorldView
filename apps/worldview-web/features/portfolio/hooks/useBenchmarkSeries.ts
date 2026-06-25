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

// R4 hardening: useMemo/useCallback stabilise the hook's outputs — see the
// closesByTicker assembly below for why identity now matters (memoized
// chart-row derivations in AnalyticsTwrChart depend on it).
import { useCallback, useMemo } from "react";
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
   *
   * R4 hardening: this object is now REFERENTIALLY STABLE across unrelated
   * re-renders (memoized via useQueries' `combine`). AnalyticsTwrChart's
   * chart-row derivation is a useMemo keyed on it — a fresh object every
   * render would silently defeat that memo.
   */
  closesByTicker: Record<string, DatedValue[]>;
  /** True while any requested ticker is resolving/fetching. */
  isLoading: boolean;
  /**
   * R4 hardening: requested tickers whose series FAILED (resolve call
   * errored, ticker resolved to no instrument, or the OHLCV fetch errored)
   * — as opposed to merely still loading. Consumers use this to render a
   * small "benchmark unavailable" notice instead of an overlay that just
   * never appears (a silent failure the user reads as a broken toggle).
   * Empty array while loading — a ticker is only declared failed once its
   * fetch chain has actually failed.
   */
  failedTickers: string[];
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
  // R4 hardening: memoised on the JOINED string because callers pass a fresh
  // array literal every render — a fresh sortedTickers each render would
  // re-create the `combine` callback below and defeat its memoisation.
  const tickersKey = [...tickers].sort().join(",");
  const sortedTickers = useMemo(
    () => (tickersKey === "" ? [] : tickersKey.split(",")),
    [tickersKey],
  );

  // ── Step 1: ticker → instrument_id (one batch round-trip) ────────────────
  // R4: isError captured — a failed resolve means EVERY requested ticker's
  // chain is dead (the OHLCV queries below never enable without an id).
  const {
    data: idMap,
    isLoading: resolveLoading,
    isError: resolveError,
  } = useQuery({
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
  //
  // R4 hardening — WHY `combine` (not a plain post-hook loop): the previous
  // implementation rebuilt closesByTicker as a fresh object on EVERY render,
  // so any consumer memo keyed on it recomputed every render (silent memo
  // defeat). `combine` is TanStack's documented memoisation channel: the
  // combined value keeps its identity until the underlying query results —
  // or the combine callback itself — actually change. The callback is a
  // useCallback keyed on the inputs it closes over (sortedTickers / idMap /
  // resolveError) so a ticker-set or resolve-state change recomputes exactly
  // once.
  const combined = useQueries({
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
    combine: useCallback(
      (
        results: Array<{
          data?: { bars?: Array<{ timestamp: string; close: number }> };
          isError: boolean;
          isLoading: boolean;
          fetchStatus: string;
        }>,
      ) => {
        // ── Assemble ticker → DatedValue[] map ───────────────────────────
        const closesByTicker: Record<string, DatedValue[]> = {};
        // R4: tickers whose chain has definitively FAILED (vs still loading).
        const failedTickers: string[] = [];
        sortedTickers.forEach((ticker, i) => {
          const result = results[i];
          const bars = result?.data?.bars;
          if (bars && bars.length > 0) {
            closesByTicker[ticker] = bars
              .map((b) => ({
                // S3 bar timestamps are "YYYY-MM-DD" (bar_date) — slice
                // defends against a full ISO datetime ever appearing so
                // date-string comparisons in alignBenchmarkToDates stay valid.
                date: b.timestamp.slice(0, 10),
                value: b.close,
              }))
              // Ascending by date — alignBenchmarkToDates requires sorted
              // input. ISO date strings sort lexicographically =
              // chronologically.
              .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
          } else if (
            // Resolve call errored → no ticker can ever fetch.
            resolveError ||
            // OHLCV fetch for this ticker errored.
            result?.isError ||
            // Resolve SUCCEEDED but this ticker has no instrument — its
            // OHLCV query is permanently disabled, so "loading" never ends.
            (idMap != null && !idMap[ticker])
          ) {
            failedTickers.push(ticker);
          }
        });
        return {
          closesByTicker,
          failedTickers,
          anyOhlcvLoading: results.some(
            (r) => r.isLoading && r.fetchStatus !== "idle",
          ),
        };
      },
      [sortedTickers, idMap, resolveError],
    ),
  });

  return {
    closesByTicker: combined.closesByTicker,
    failedTickers: combined.failedTickers,
    isLoading: enabled && (resolveLoading || combined.anyOhlcvLoading),
  };
}
