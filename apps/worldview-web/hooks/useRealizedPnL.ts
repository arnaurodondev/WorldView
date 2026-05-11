/**
 * hooks/useRealizedPnL.ts — Realized P&L query hook (PLAN-0051 T-A-1-05)
 *
 * WHY THIS EXISTS: The PortfolioKPIStrip currently renders a *client-computed*
 * realized P&L approximation (sum of (sell_price − current_avg_cost) × qty
 * across SELL transactions) which has two well-documented holes:
 *
 *   1. Closed positions silently drop out: once the last share is sold, the
 *      `holdings` row vanishes, so the client can no longer recover the cost
 *      basis of the closed lot. Long-since-closed winning trades disappear
 *      from the trader's realized number — exactly the trades they want to
 *      see most.
 *   2. The client uses the *current* average cost, not the FIFO cost at the
 *      time of each individual sale. For partially-closed positions the two
 *      numbers diverge when later buys happen at different prices.
 *
 * S1's new GET /v1/portfolios/{id}/realized-pnl endpoint (T-A-1-04) computes
 * FIFO over the full transaction history server-side and additionally splits
 * the total into long-term vs short-term. Wiring the strip to that endpoint
 * removes both bugs in one step.
 *
 * WHY a dedicated hook (not inline useQuery in the page): two consumers need
 * the value — the KPI strip and the (future) realized-P&L drill-down panel.
 * Centralising the staleTime / queryKey conventions here means TanStack Query
 * dedupes the request across both consumers automatically.
 *
 * STALE-TIME CITATION: 60 000 ms = 1 minute. Why this number specifically:
 *   • Realized P&L is mechanically a function of completed transactions.
 *   • Within an active session a trader rarely places more than one closing
 *     trade per minute, so the value is effectively steady on a sub-minute
 *     timescale.
 *   • The S1 FIFO computation is cheap (~10 ms even with 5k transactions)
 *     so we could refetch more aggressively, BUT the visual *flicker* a
 *     short stale-time produces (every tab focus refetches and momentarily
 *     shows a spinner) is more harmful than the lag of a 1-minute window.
 *   • Mutations that change the value (a new SELL, a CSV transaction
 *     import) explicitly invalidate the ["realized-pnl"] key, so the user
 *     never has to wait the full minute for a freshly-recorded trade to
 *     appear — the staleTime is only the *passive refresh* cadence.
 *
 * WHY no refetchInterval: passive 1-minute polling on a value that only
 * changes at trade-execution moments would burn S1 cycles for nothing.
 * Triggering on tab-focus and explicit invalidation is sufficient.
 *
 * WHO USES IT:
 *   - components/portfolio/PortfolioKPIStrip wrapper in app/(app)/portfolio/page.tsx
 *
 * DATA SOURCE: GET /v1/portfolios/{portfolio_id}/realized-pnl?from=&to=
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { RealizedPnLResponse } from "@/types/api";

/**
 * Default date range: current calendar year, Jan 1 → today, ISO YYYY-MM-DD.
 *
 * WHY current calendar year (not "all time" / not "30 days"):
 * traders think about realized P&L in tax-year terms. The current calendar
 * year is the most useful default because it matches the way 1099-B
 * paperwork will arrive in February. Power users can override the range.
 *
 * Exported so tests and the page header can render the same window the
 * hook is querying.
 */
export function defaultRealizedPnLRange(now: Date = new Date()): {
  from: string;
  to: string;
} {
  const year = now.getFullYear();
  // YYYY-MM-DD computed in the trader's local timezone — see csv-export
  // helper for the same rationale (a trade at 23:30 PST belongs to today,
  // not tomorrow's UTC date).
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return {
    from: `${year}-01-01`,
    to: `${year}-${mm}-${dd}`,
  };
}

/**
 * useRealizedPnL — TanStack Query wrapper around getRealizedPnL.
 *
 * @param portfolioId  S1 portfolio ID, or undefined while still loading
 * @param from         Optional ISO date "YYYY-MM-DD" lower bound
 * @param to           Optional ISO date "YYYY-MM-DD" upper bound
 *
 * WHY return the full UseQueryResult: the strip reads `data` for the value
 * and `isError` for the "approx." badge. Returning the raw query object
 * keeps the API minimal and lets future consumers also read `isLoading`,
 * `error`, etc. without us having to widen the hook return-type later.
 */
export function useRealizedPnL(
  portfolioId: string | null | undefined,
  from?: string,
  to?: string,
): UseQueryResult<RealizedPnLResponse, Error> {
  const { accessToken, isAuthenticated } = useAuth();

  return useQuery<RealizedPnLResponse, Error>({
    // WHY include the date range in the key: the same portfolio with a
    // different window produces a completely different number. Sharing
    // a key across windows would silently serve stale data.
    queryKey: ["realized-pnl", portfolioId, from, to],
    queryFn: () => createGateway(accessToken).getRealizedPnL(portfolioId!, from, to),
    // Gate on portfolioId presence — we should NEVER fire the request with
    // `undefined` because the URL would 404 on the path-encode step.
    enabled: !!accessToken && isAuthenticated && !!portfolioId,
    staleTime: 60_000, // 1 min — see file header for the rationale
    // WHY no retry on 404 / 503: if the endpoint isn't deployed yet (the
    // backend half of T-A-1-04 lands later), we want isError=true on the
    // first response so the strip can show the "approx." badge instead of
    // looping forever. Status-aware retry is overkill — the user can hard
    // refresh the page if they need an explicit retry.
    retry: false,
  });
}
