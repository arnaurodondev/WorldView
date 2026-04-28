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
 * WHY 15s (was 30s): institutional traders expect their account header to
 * track the live tape. A 30s lag is visible — the user clicks "Buy" then
 * waits 30s for the rail to acknowledge the new position. 15s halves that
 * worst-case visible lag while keeping the underlying batch quote endpoint
 * well within its rate budget (a single instrument list per refresh).
 *
 * Why TanStack Query (not setInterval): the hook composes three S9 queries
 * (portfolios → holdings → batch quotes) that already share their query keys
 * with PortfolioSummary and the dashboard. Reusing the same keys means
 * TanStack dedupes the HTTP requests across consumers — even with the layout
 * AND PortfolioSummary AND a future account widget all calling this hook,
 * we never fire more than one batch-quote refresh per 15s window.
 *
 * Returns nullable values during the loading window because the TopBar slots
 * stay visually empty (a hidden value) until real data is known — better than
 * showing "$0.00" which technically lies about the account state.
 */

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

/** Snapshot of the user's portfolio at a moment in time, for the TopBar rail. */
export interface PortfolioMetrics {
  /** Total mark-to-market value (sum of qty × live_price). null while loading. */
  portfolioValue: number | null;
  /** Today's intraday P&L (sum of qty × per-share daily change). null while loading. */
  dailyPnl: number | null;
  /** Total unrealised P&L (mark-to-market value − cost basis). null while loading. */
  unrealisedPnl: number | null;
  /** True until at least the holdings query has resolved — useful for skeleton timing. */
  isLoading: boolean;
}

/** Refresh cadence for live quote-based metrics. See WHY 15s in the file header. */
const QUOTE_REFETCH_MS = 15_000;
/** Holdings/positions cadence — slower because shape changes only on trades. */
const HOLDINGS_REFETCH_MS = 30_000;

/**
 * usePortfolioMetrics — composite hook returning the live portfolio header.
 *
 * Composes:
 *   1. GET /v1/portfolios            — pick the first portfolio (single-portfolio MVP)
 *   2. GET /v1/portfolios/{id}/holdings
 *   3. POST /v1/quotes/batch         — refreshed every 15s during the trading day
 *
 * The hook is layer-thin: the original layout-level math (NAV / day P&L /
 * unrealised) was already correct, we just move it here so any caller gets
 * the same answers from the same query cache.
 */
export function usePortfolioMetrics(): PortfolioMetrics {
  const { accessToken, isAuthenticated } = useAuth();

  // WHY share the EXACT query key with PortfolioSummary and the dashboard:
  // TanStack Query dedupes by key, so multiple consumers of this hook share a
  // single HTTP fetch. Changing the key here would silently double-fire queries.
  const { data: portfoliosData } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken && isAuthenticated,
    staleTime: 60_000,
  });
  const firstPortfolioId = portfoliosData?.[0]?.portfolio_id;

  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings", firstPortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(firstPortfolioId!),
    enabled: !!accessToken && isAuthenticated && !!firstPortfolioId,
    staleTime: HOLDINGS_REFETCH_MS,
  });

  const navInstrumentIds = holdingsResp?.holdings.map((h) => h.instrument_id) ?? [];

  // The 15s window is a deliberate, plan-mandated cadence (T-A-1-02).
  const { data: navQuotes } = useQuery({
    queryKey: ["holdings-quotes", navInstrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(navInstrumentIds),
    enabled: navInstrumentIds.length > 0 && !!accessToken && isAuthenticated,
    staleTime: QUOTE_REFETCH_MS,
    refetchInterval: QUOTE_REFETCH_MS,
  });

  // ── Derive the rail values ──────────────────────────────────────────────────
  // WHY null when no holdings: the TopBar slot then renders empty — better than
  // "$0.00" which would lie ("nothing" vs "definitely zero").
  const portfolioValue: number | null = holdingsResp?.holdings.length
    ? holdingsResp.holdings.reduce((sum, h) => {
        const quote = navQuotes?.quotes?.[h.instrument_id];
        // Fall back to average_cost when the quote hasn't arrived yet so the NAV
        // doesn't flicker to a partial sum during the 15s refetch tick.
        const price = quote?.price ?? h.average_cost;
        return sum + price * h.quantity;
      }, 0)
    : null;

  // Day P&L = sum across holdings of (per-share daily change × qty).
  // Missing change => 0 contribution, so the value snaps to truth once quotes resolve.
  const dailyPnl: number | null = holdingsResp?.holdings.length
    ? holdingsResp.holdings.reduce((sum, h) => {
        const q = navQuotes?.quotes?.[h.instrument_id];
        return sum + (q?.change ?? 0) * h.quantity;
      }, 0)
    : null;

  // Total P&L (Unrealised) = mark-to-market − cost basis.
  // Use h.average_cost (NOT q.price) for cost — cost basis is locked at trade time.
  const totalCost: number =
    holdingsResp?.holdings.reduce((s, h) => s + h.average_cost * h.quantity, 0) ?? 0;
  const unrealisedPnl: number | null =
    portfolioValue != null ? portfolioValue - totalCost : null;

  return {
    portfolioValue,
    dailyPnl,
    unrealisedPnl,
    isLoading: holdingsLoading,
  };
}
