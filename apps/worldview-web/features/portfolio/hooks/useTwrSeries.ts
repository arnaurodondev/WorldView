/**
 * features/portfolio/hooks/useTwrSeries.ts — shared TanStack query for the
 * flow-adjusted TWR series (2026-06-10 sprint gap #3).
 *
 * WHY A SHARED HOOK (not inline useQuery in each consumer): two surfaces
 * read the same series for overlapping windows:
 *   1. AnalyticsTwrChart — draws the TWR line (+ optional NAV-return line).
 *   2. PerformancePeriodsPanel — computes 1D/1W/1M/3M returns from the
 *      cumulative series deltas.
 * Centralizing the queryKey (qk.portfolios.twr) means both consumers with
 * the same (portfolioId, days) share ONE cache entry / network round-trip,
 * and a future mutation-side invalidation has a single key family to target.
 *
 * STALENESS: 60s — the S1 series is snapshot-based (daily NAV + flow
 * markers); intra-minute refetching cannot produce new points.
 *
 * PLACEHOLDER DATA: period switches change `days` (a new key); carrying the
 * previous window forward keeps charts drawn during the refetch instead of
 * flashing a skeleton (same R3-polish convention as the value-history
 * consumers in AnalyticsTab).
 *
 * WHO USES IT: AnalyticsTwrChart, PerformancePeriodsPanel.
 */

"use client";
// WHY "use client": TanStack Query requires the QueryClientProvider context.

import { useQuery } from "@tanstack/react-query";

// WHY createGateway + useAuth (NOT useApiClient): this hook is mounted on the
// DEFAULT Holdings tab (PerformancePeriodsPanel). The overview surface — and
// every page-level test of it — is built on the createGateway pattern
// (usePortfolioData, useExposure, RecentActivityStrip); useApiClient requires
// an ApiClientProvider that the overview's render tree/tests don't guarantee.
// The two clients return identical data, so cache entries stay compatible.
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import type { TwrResponse } from "@/types/api";

export interface UseTwrSeriesArgs {
  /** Portfolio UUID — null disables the query (no fabricated fetches). */
  portfolioId: string | null | undefined;
  /**
   * Lookback window in days (1–3650). undefined = server default (90).
   * Part of the cache key — each window is a distinct server computation
   * (the series rebases to 0 at window start).
   */
  days?: number;
  /** External gate (default true) for callers that mount eagerly. */
  enabled?: boolean;
}

export function useTwrSeries({ portfolioId, days, enabled = true }: UseTwrSeriesArgs) {
  const { accessToken } = useAuth();

  return useQuery<TwrResponse>({
    queryKey: qk.portfolios.twr(portfolioId ?? "", days),
    queryFn: () => createGateway(accessToken).getTwr(portfolioId!, days),
    enabled: enabled && Boolean(portfolioId) && Boolean(accessToken),
    staleTime: 60_000,
    // Keep the previous window's series rendered (dimmed by consumers via
    // isPlaceholderData) while the new window loads — no skeleton flash.
    placeholderData: (prev) => prev,
  });
}
