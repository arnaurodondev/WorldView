/**
 * features/portfolio/hooks/usePortfolioBundle.ts — Portfolio page bundle hook
 *
 * WHY THIS HOOK EXISTS (PLAN-0070 C-1):
 * The portfolio page previously made N individual requests on cold start to
 * populate its sub-sections (portfolio metadata, holdings, transactions,
 * value-history, etc.). This hook replaces those with a single bundle request
 * to `GET /v1/portfolio/{id}/bundle` that fans out to all sub-resources
 * server-side (inside S9's asyncio.gather) and returns the results in one
 * response.
 *
 * BENEFITS:
 *   1. Cold-start latency: N sequential round-trips → 1 bundle round-trip
 *      (~80–120ms total vs 4× ~50ms sequential = ~200ms or worse with waterfall)
 *   2. Network: 1 TLS handshake + 1 TCP round-trip instead of N
 *   3. Partial failure is handled server-side: if holdings fails, the other
 *      legs still return. _meta.partial=true signals degraded data.
 *
 * IMPORTANT — what this hook does NOT do:
 *   - It does NOT replace the existing usePortfolioData hook.
 *     usePortfolioData.ts is still the primary orchestrator for the portfolio
 *     page and carries all the derived state (kpi, allocations, enrichedHoldings,
 *     mutations, etc.). This hook is ADDITIVE — it provides a single-fetch
 *     shortcut for NEW consumers that want a fast initial load.
 *   - It does NOT transform the raw bundle data into fully-typed frontend shapes.
 *     The bundle legs return raw S1 JSON. Use the dedicated hooks (useQuery +
 *     getHoldings/getTransactions) when you need the transformed, typed shapes.
 *
 * USAGE:
 *   const { data: bundle, isLoading, isError } = usePortfolioBundle({
 *     portfolioId: "some-uuid",
 *     accessToken: "bearer-token",
 *   });
 *   if (bundle?.portfolio) {
 *     // portfolio metadata is available immediately
 *   }
 */

"use client";
// WHY "use client": useQuery and useQueryClient are React hooks that only
// run in the browser. Server components cannot use TanStack Query.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import type { PortfolioBundleResponse } from "@/types/api";

// ── Hook contract ─────────────────────────────────────────────────────────────

export interface UsePortfolioBundleArgs {
  /**
   * UUID of the portfolio to fetch. When null, the query is disabled.
   * Passing null allows components to mount before portfolio selection
   * resolves without triggering a fetch for an empty ID.
   */
  portfolioId: string | null;
  /**
   * Bearer token from useAuth(). When null, the query is disabled.
   * Token lives in React state only — never localStorage (CLAUDE.md Rule 8).
   */
  accessToken: string | null;
}

// ── usePortfolioBundle ────────────────────────────────────────────────────────

/**
 * usePortfolioBundle — single-request portfolio page data loader.
 *
 * Returns a standard TanStack Query result so the caller can use
 * isLoading / isError / data in the usual way.
 *
 * staleTime=30_000: bundle data is valid for 30s. Portfolio metadata
 * (name, currency) is stable; holdings change only on transactions;
 * value-history changes at 21:30 UTC daily snapshot. 30s is a safe
 * balance between freshness and network efficiency.
 *
 * refetchOnWindowFocus=false: the bundle is large (~5 KB). Refetching
 * every time the user tabs back in would be wasteful given the 30s
 * staleTime. Mutations should call invalidateAll() instead.
 */
export function usePortfolioBundle({ portfolioId, accessToken }: UsePortfolioBundleArgs) {
  return useQuery<PortfolioBundleResponse>({
    queryKey: qk.portfolios.bundle(portfolioId ?? ""),
    queryFn: () => createGateway(accessToken).getPortfolioBundle(portfolioId!),
    // WHY double-guard: portfolioId="" (empty string fallback) would send a
    // malformed request. Both guards are required — null OR empty string skips.
    enabled: !!portfolioId && !!accessToken,
    staleTime: 30_000,
    // WHY false: avoid a full 5 KB round-trip on every window focus.
    // Mutations that change portfolio state call invalidateAll() explicitly.
    refetchOnWindowFocus: false,
  });
}

// ── usePortfolioBundleInvalidation ────────────────────────────────────────────

/**
 * usePortfolioBundleInvalidation — returns invalidation callbacks that
 * cascade all bundle-derived queries after mutations.
 *
 * WHY: when a transaction is added, the portfolio's holdings, transactions,
 * and value-history all change. Invalidating the bundle key causes the
 * entire bundle to refetch with fresh data. We also invalidate the flat
 * legacy keys that usePortfolioData uses so both hooks stay in sync.
 *
 * USAGE:
 *   const { invalidateAll } = usePortfolioBundleInvalidation(portfolioId);
 *   // After a successful POST /transactions:
 *   await invalidateAll();
 */
export function usePortfolioBundleInvalidation(portfolioId: string | null) {
  const queryClient = useQueryClient();

  const invalidateAll = async () => {
    if (!portfolioId) return;

    // WHY bundle key first: triggers the bundle refetch so the next render
    // already has fresh data when the other invalidations resolve.
    await queryClient.invalidateQueries({
      queryKey: qk.portfolios.bundle(portfolioId),
    });

    // WHY also invalidate flat legacy keys: usePortfolioData.ts uses
    // holdingsByPortfolio/transactionsByPortfolio (not the bundle key).
    // Both hooks must stay in sync so data doesn't diverge if both are
    // mounted at the same time (e.g., during a gradual migration period).
    await queryClient.invalidateQueries({
      queryKey: qk.portfolios.holdingsByPortfolio(portfolioId),
    });
    await queryClient.invalidateQueries({
      queryKey: qk.portfolios.transactionsByPortfolio(portfolioId),
    });
  };

  return { invalidateAll };
}
