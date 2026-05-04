/**
 * features/dashboard/hooks/useDashboardSnapshot.ts — Dashboard snapshot hook
 *
 * WHY THIS HOOK EXISTS (PLAN-0070 C-2):
 * The dashboard previously triggered 6+ individual data-fetching requests on
 * cold start (news, heatmap, prediction markets, earnings, alerts, morning brief).
 * This hook replaces those with a single bundle request to
 * `GET /v1/dashboard/snapshot` that fans out to all 6 sub-resources server-side
 * (inside S9's asyncio.gather) and returns them in one response.
 *
 * BENEFITS:
 *   1. Cold-start latency: 6+ parallel round-trips → 1 bundle round-trip
 *      (~80–120ms total vs 6× ~50ms parallel = same in best case, but saves
 *      6 TLS handshakes and TCP round-trips per page load)
 *   2. Network: 1 TLS handshake + 1 TCP round-trip instead of 6+
 *   3. Partial failure is handled server-side: if alerts fail, the other 5
 *      legs still return. _meta.partial=true signals degraded data.
 *
 * USAGE — per-widget slice access via the `select` option:
 *   // Get only the news leg — avoids re-renders when other legs update
 *   const { data: news } = useDashboardSnapshot({ select: (d) => d?.news });
 *
 *   // Get the full bundle
 *   const { data, isLoading, isError } = useDashboardSnapshot();
 *
 * IMPORTANT — what this hook does NOT do:
 *   - It does NOT replace individual widget hooks for movers / watchlist.
 *     Those require per-instrument lookups (N quote calls) that cannot be
 *     batched without knowing the user's watchlist members first.
 *   - It does NOT transform the raw bundle data into fully-typed frontend shapes.
 *     The bundle legs return raw JSON from upstream. Widgets that need heavier
 *     transformation should continue using their dedicated query hooks until
 *     a migration wave wires them to the snapshot.
 *   - It does NOT modify dashboard/page.tsx — this wave is additive.
 *     Widgets can optionally migrate to the snapshot in a future wave.
 */

// WHY "use client": useQuery is a React hook that only runs in the browser.
// Server components cannot use TanStack Query — any component that imports
// this hook must itself be a Client Component.
"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
import type { DashboardSnapshotResponse } from "@/types/api";

/**
 * useDashboardSnapshot — single-request dashboard page data loader.
 *
 * Generic parameter T defaults to DashboardSnapshotResponse. Pass `select`
 * to derive a narrower type and avoid re-renders from unrelated leg updates:
 *
 *   // Only re-renders when `news` changes (not when `alerts` changes)
 *   const { data: news } = useDashboardSnapshot({ select: (d) => d?.news });
 *
 * staleTime=30_000: 30s. News and alerts change frequently, but a 30s window
 * avoids hammering the gateway on every minor interaction. The individual
 * widget hooks (e.g. useRecentAlerts) refetch more aggressively if needed.
 *
 * refetchOnWindowFocus=false: the snapshot bundle is large (~5–10 KB across
 * 6 upstream responses). Tab switching should NOT re-fetch all of it — the
 * 30s staleTime is already a fresh enough signal. Individual widgets that
 * need live alerts/prices should use their own focused hooks.
 */
export function useDashboardSnapshot<T = DashboardSnapshotResponse>(options?: {
  /**
   * Selector to extract a sub-slice from the full bundle.
   *
   * WHY select: TanStack Query's `select` option runs the transform after the
   * fetch but before triggering a re-render. Components that only care about
   * one leg (e.g. `d?.news`) are isolated from re-renders caused by updates
   * to unrelated legs (e.g. `d?.alerts`). This is the canonical TanStack
   * pattern for "subscribe to only part of a large response".
   */
  select?: (data: DashboardSnapshotResponse | undefined) => T;
}) {
  // WHY useAuth inside the hook (not passed as a prop): co-locating the token
  // lookup with the hook keeps callers simple — they don't need to know where
  // the token comes from. The token lives in AuthContext React state only
  // (never localStorage — CLAUDE.md Rule 8).
  const { accessToken } = useAuth();

  return useQuery<DashboardSnapshotResponse, Error, T>({
    queryKey: qk.dashboard.snapshot(),
    // WHY createGateway inside queryFn: the gateway factory binds the current
    // access token at call time. If the token refreshes between renders, the
    // next refetch automatically uses the fresh token without requiring a
    // re-mount or prop update.
    queryFn: () => createGateway(accessToken).getDashboardSnapshot(),
    // WHY enabled guard: prevents a fetch with an undefined token, which would
    // trigger a 401 from S9's auth guard and pollute the error boundary.
    enabled: !!accessToken,
    staleTime: 30_000,
    // WHY false: see module JSDoc above. The snapshot is heavy; tab focus
    // should not trigger a full 6-leg re-fetch.
    refetchOnWindowFocus: false,
    select: options?.select,
  });
}
