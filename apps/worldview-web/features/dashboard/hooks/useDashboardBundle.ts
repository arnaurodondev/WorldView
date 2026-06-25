/**
 * features/dashboard/hooks/useDashboardBundle.ts — F-2 single composite hook
 *
 * WHY THIS HOOK EXISTS (F-2):
 * The dashboard page previously fired N independent per-widget queries on cold
 * start (morning brief, top movers gainers, top movers losers, sector heatmap,
 * recent alerts, portfolio summary). Each query is its own round-trip with its
 * own TLS handshake budget — the page is wave-serialized by the slowest leg.
 *
 * This hook fires a SINGLE request to GET /v1/dashboard/bundle that fans out
 * to all 6 upstream services server-side via asyncio.gather. The dashboard
 * page then HYDRATES the existing per-widget TanStack query caches from the
 * bundle's legs via queryClient.setQueryData, so the child widgets render
 * without firing their own initial fetches.
 *
 * USAGE:
 *   const { data: bundle } = useDashboardBundle();
 *   useEffect(() => {
 *     if (!bundle) return;
 *     queryClient.setQueryData(qk.dashboard.morningBrief(), bundle.brief);
 *     // … etc.
 *   }, [bundle, queryClient]);
 *
 * IMPORTANT — what this hook does NOT do:
 *   - It does NOT remove or replace the per-widget endpoints. The widgets
 *     continue using their own hooks for refresh and sub-page navigation;
 *     the bundle is purely an initial-load optimisation.
 *   - It does NOT transform the bundle legs. Pass-through JSON from upstream
 *     is hydrated as-is into per-widget caches.
 */

// WHY "use client": useQuery is a React hook that only runs in the browser.
// Any component that imports this hook must itself be a Client Component.
"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
import type { DashboardBundleResponse } from "@/lib/api/dashboard";

/**
 * useDashboardBundle — fetches the F-2 composite bundle once for the page.
 *
 * staleTime=30_000: dashboard data freshens often (alerts, prices). 30s keeps
 * the cache hot during normal navigation between tabs without hammering the
 * gateway on every micro-interaction.
 *
 * enabled=!!accessToken: prevents a fetch with an undefined token, which
 * would 401 from S9's auth guard and pollute the error boundary.
 *
 * refetchOnWindowFocus=false: the bundle is large; tab-switching should not
 * trigger a full 6-leg re-fetch. Individual widgets that need live data can
 * use their own focused hooks (qk.alerts.list(), qk.dashboard.aiSignals(), …).
 */
export function useDashboardBundle() {
  // WHY useAuth inside the hook (not passed as a prop): co-locating the token
  // lookup with the hook keeps callers simple — they don't need to know where
  // the token comes from. The token lives in AuthContext React state only
  // (never localStorage — CLAUDE.md Rule 8).
  const { accessToken } = useAuth();

  return useQuery<DashboardBundleResponse>({
    queryKey: qk.dashboard.bundle(),
    // WHY createGateway inside queryFn: the gateway factory binds the current
    // access token at call time. If the token refreshes between renders, the
    // next refetch automatically uses the fresh token without re-mounting.
    queryFn: () => createGateway(accessToken).getDashboardBundle(),
    enabled: !!accessToken,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
