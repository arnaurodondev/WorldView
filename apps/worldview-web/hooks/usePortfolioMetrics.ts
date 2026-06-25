/**
 * hooks/usePortfolioMetrics.ts — Hoisted portfolio NAV + P&L hook
 *
 * WHY THIS EXISTS (PLAN-0050 T-A-1-02): The TopBar's portfolio rail (PORT,
 * Day P&L, Total P&L) was previously computed inline inside `app/(app)/layout.tsx`.
 * That worked, but it bound the computation to one layout file, made the
 * 30s refresh cadence implicit, and meant other consumers (e.g. an account
 * panel, an Ask AI prompt) could not reuse the same numbers without
 * re-implementing the chain. Extracting to a single hook gives one source of
 * truth and lets us bump the refetchInterval to 15s (the cadence the plan
 * audit demands) in a single place.
 *
 * ── "ALL PORTFOLIOS" AGGREGATION (2026-06-10 PortfolioSwitcher fix) ────────
 * The TopBar chip's selection semantics are now honoured end-to-end:
 *   - activePortfolioId === <uuid>  → metrics scope to THAT portfolio only.
 *   - activePortfolioId === null ("All Portfolios"):
 *       * if a ROOT portfolio exists (kind === "root", PLAN-0046 aggregate),
 *         use its holdings — the backend-supported aggregate.
 *       * otherwise AGGREGATE CLIENT-SIDE: fan out one holdings query per
 *         portfolio (shared ["holdings", id] cache keys, so per-portfolio
 *         widgets on the same page reuse the responses) and sum the rail
 *         values across all of them. The previous behaviour silently showed
 *         portfolios[0] under the "All Portfolios" label — a lie for any
 *         user with 2+ portfolios.
 *
 * WHY 15s (was 30s): institutional traders expect their account header to
 * track the live tape. 15s halves the worst-case visible lag while keeping
 * the batch quote endpoint well within its rate budget.
 *
 * Why TanStack Query (not setInterval): the queries share their keys with
 * PortfolioSummary and the dashboard, so TanStack dedupes the HTTP requests
 * across consumers — we never fire more than one batch-quote refresh per
 * 15s window no matter how many components call this hook.
 *
 * Returns nullable values during the loading window because the TopBar slots
 * stay visually empty (a hidden value) until real data is known — better than
 * showing "$0.00" which technically lies about the account state.
 */

import { useQuery, useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { useActivePortfolio } from "@/contexts/ActivePortfolioContext";
import type { HoldingsResponse } from "@/types/api";

/** Snapshot of the user's portfolio at a moment in time, for the TopBar rail. */
export interface PortfolioMetrics {
  /** Total mark-to-market value (sum of qty × live_price). null while loading. */
  portfolioValue: number | null;
  /** Today's intraday P&L (sum of qty × per-share daily change). null while loading. */
  dailyPnl: number | null;
  /** Total unrealised P&L (mark-to-market value − cost basis). null while loading. */
  unrealisedPnl: number | null;
  /** True until at least the holdings queries have resolved — useful for skeleton timing. */
  isLoading: boolean;
}

/**
 * Refresh cadence for live quote-based metrics. See WHY 15s in the file header.
 * Exported (F-QA-21) so PortfolioSummary and LiveQuoteBadge can pin to the same
 * value — drift between consumers caused F-QA-01 when PortfolioSummary kept
 * `staleTime: 0` after this hook landed.
 */
export const QUOTE_REFETCH_MS = 15_000;
/** Holdings/positions cadence — slower because shape changes only on trades. */
export const HOLDINGS_REFETCH_MS = 30_000;

/**
 * usePortfolioMetrics — composite hook returning the live portfolio header.
 *
 * Composes:
 *   1. GET /v1/portfolios                 — full list (also resolves the scope)
 *   2. GET /v1/portfolios/{id}/holdings   — one per portfolio in scope
 *   3. POST /v1/quotes/batch              — refreshed every 15s, union of holdings
 */
export function usePortfolioMetrics(): PortfolioMetrics {
  const { accessToken, isAuthenticated } = useAuth();
  // The TopBar PortfolioSwitcher writes here; null = "All Portfolios".
  const { activePortfolioId } = useActivePortfolio();

  // QA A-F-001 (2026-05-21) — central qk.portfolios.list() factory so the
  // PortfolioSwitcher / PortfolioSummary / bundle hydrator share ONE cache
  // entry (the bare ["portfolios"] key used to fork the cache → 2 fetches).
  const { data: portfoliosData } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken && isAuthenticated,
    staleTime: 60_000,
  });

  // ── Resolve the SCOPE: which portfolio ids feed the rail ──────────────────
  // Mirrors useResolvedPortfolioId's stale-id guard (selection must still
  // exist in the list) but extends the null/"All" branch to a true aggregate.
  const scopeIds: string[] = useMemo(() => {
    const portfolios = portfoliosData ?? [];
    if (portfolios.length === 0) return [];
    // Explicit single-portfolio selection (and it still exists) → scope to it.
    if (
      activePortfolioId &&
      portfolios.some((p) => p.portfolio_id === activePortfolioId)
    ) {
      return [activePortfolioId];
    }
    // "All Portfolios": prefer the backend ROOT aggregate when provisioned
    // (PLAN-0046) — its holdings already represent the whole household.
    const root = portfolios.find((p) => p.kind === "root");
    if (root) return [root.portfolio_id];
    // No ROOT row → client-side aggregate across every portfolio. For the
    // common single-portfolio account this degenerates to exactly the old
    // portfolios[0] behaviour (one holdings query, same cache key).
    return portfolios.map((p) => p.portfolio_id);
  }, [portfoliosData, activePortfolioId]);

  // ── Holdings: one query per portfolio in scope ────────────────────────────
  // WHY ["holdings", id] keys: identical to PortfolioSummary /
  // WatchlistQuickViewWidget / HoldingsMoversWidget — when those widgets are
  // mounted on the same page the fetches dedupe to zero extra requests.
  const holdingsQueries = useQueries({
    queries: scopeIds.map((id) => ({
      queryKey: ["holdings", id],
      queryFn: () => createGateway(accessToken).getHoldings(id),
      enabled: !!accessToken && isAuthenticated,
      staleTime: HOLDINGS_REFETCH_MS,
    })),
  });

  // Merge holdings across the scope. A position held in two portfolios stays
  // as two rows — the reduce below sums contributions, which is exactly the
  // aggregate semantics ("household exposure"), and the quote lookup keys by
  // instrument_id so both rows price off the same quote.
  const mergedHoldings = useMemo(
    () =>
      holdingsQueries.flatMap(
        (q) => (q.data as HoldingsResponse | undefined)?.holdings ?? [],
      ),
    [holdingsQueries],
  );

  const holdingsLoading =
    scopeIds.length === 0 || holdingsQueries.some((q) => q.isLoading);
  // "Resolved" = every holdings query in scope has an answer. Guards the
  // null-vs-zero distinction below: we only declare "no holdings" (null rail)
  // once we have actually heard back from every portfolio in scope.
  const holdingsResolved =
    scopeIds.length > 0 && holdingsQueries.every((q) => q.data !== undefined);

  // Union of instrument ids across the scope (Set dedupes cross-portfolio
  // overlap so the batch-quote payload stays minimal).
  const navInstrumentIds = useMemo(
    () => [...new Set(mergedHoldings.map((h) => h.instrument_id))],
    [mergedHoldings],
  );

  // The 15s window is a deliberate, plan-mandated cadence (T-A-1-02).
  const { data: navQuotes } = useQuery({
    // WHY qk.portfolios.holdingsQuotesByIds (not inline array): the factory sorts
    // the IDs so [A,B] and [B,A] share the same cache entry — prevents orphaned
    // cache entries when the holdings API returns instruments in different order
    // across fetches (F-DS-002, QA 2026-05-21).
    queryKey: qk.portfolios.holdingsQuotesByIds(navInstrumentIds),
    queryFn: () => createGateway(accessToken).getBatchQuotes(navInstrumentIds),
    enabled: navInstrumentIds.length > 0 && !!accessToken && isAuthenticated,
    staleTime: QUOTE_REFETCH_MS,
    refetchInterval: QUOTE_REFETCH_MS,
  });

  // ── Derive the rail values ──────────────────────────────────────────────────
  // WHY null when no holdings: the TopBar slot then renders empty — better than
  // "$0.00" which would lie ("nothing" vs "definitely zero").
  const hasHoldings = holdingsResolved && mergedHoldings.length > 0;

  const portfolioValue: number | null = hasHoldings
    ? mergedHoldings.reduce((sum, h) => {
        const quote = navQuotes?.quotes?.[h.instrument_id];
        // Fall back to average_cost when the quote hasn't arrived yet so the NAV
        // doesn't flicker to a partial sum during the 15s refetch tick.
        const price = quote?.price ?? h.average_cost;
        return sum + price * h.quantity;
      }, 0)
    : null;

  // Day P&L = sum across holdings of (per-share daily change × qty).
  // Missing change => 0 contribution, so the value snaps to truth once quotes resolve.
  const dailyPnl: number | null = hasHoldings
    ? mergedHoldings.reduce((sum, h) => {
        const q = navQuotes?.quotes?.[h.instrument_id];
        return sum + (q?.change ?? 0) * h.quantity;
      }, 0)
    : null;

  // Total P&L (Unrealised) = mark-to-market − cost basis.
  // Use h.average_cost (NOT q.price) for cost — cost basis is locked at trade time.
  const totalCost: number = mergedHoldings.reduce(
    (s, h) => s + h.average_cost * h.quantity,
    0,
  );
  const unrealisedPnl: number | null =
    portfolioValue != null ? portfolioValue - totalCost : null;

  return {
    portfolioValue,
    dailyPnl,
    unrealisedPnl,
    isLoading: holdingsLoading,
  };
}
