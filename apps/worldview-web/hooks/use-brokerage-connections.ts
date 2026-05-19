/**
 * hooks/use-brokerage-connections.ts — TanStack Query hooks for brokerage connections
 *
 * WHY THIS EXISTS: Encapsulates all data-fetching and mutation logic for the
 * SnapTrade brokerage integration. Components import these hooks instead of
 * calling createGateway() directly, keeping query key management and
 * invalidation logic in a single place.
 *
 * HOW QUERY KEYS WORK:
 *   ["brokerage-connections", portfolioId] — per-portfolio connection list
 *   ["sync-errors", connectionId]          — per-connection error list
 * Mutations invalidate these keys so the UI reflects changes automatically.
 *
 * WHO USES IT:
 *   - components/brokerage/ConnectedBrokeragesList.tsx (list + sync + disconnect)
 *   - components/brokerage/ConnectBrokerageModal.tsx (initiate mutation)
 *   - components/brokerage/SyncErrorsBanner.tsx (sync errors query)
 *
 * DATA SOURCE: lib/gateway.ts brokerage methods → S9 /api/v1/brokerage-connections
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

// ── Read hooks ────────────────────────────────────────────────────────────────

/**
 * useBrokerageConnections — query brokerage connections for the authenticated user.
 *
 * WHY staleTime 30s: connections don't change frequently (only on sync or
 * explicit user action). 30s avoids redundant refetches while keeping the list
 * reasonably fresh when the user switches tabs or returns to the portfolio page.
 *
 * WHY refetchInterval 60s: a background sync may update last_synced_at and status
 * between user interactions. 60s polling ensures the list reflects sync progress
 * without overwhelming S9 with requests.
 *
 * @param portfolioId - optional; when provided, filters to a single portfolio
 */
export function useBrokerageConnections(portfolioId?: string) {
  const { accessToken } = useAuth();

  return useQuery({
    // WHY portfolioId in queryKey: React Query caches per key. Different
    // portfolioId values get separate cache entries, so switching portfolios
    // doesn't serve stale data from a different portfolio.
    queryKey: ["brokerage-connections", portfolioId ?? null],
    queryFn: () => createGateway(accessToken).getBrokerageConnections(portfolioId),
    enabled: !!accessToken,
    staleTime: 30_000,   // 30 seconds — connections change infrequently
    refetchInterval: 60_000, // poll every 60s to catch async sync status updates
  });
}

/**
 * useSyncErrors — query transaction-level sync errors for a single connection.
 *
 * WHY enabled guard: we only fetch errors when there IS a connectionId to fetch
 * for. An empty string or undefined connectionId would send a malformed request.
 * The SyncErrorsBanner passes its connectionId prop here — it's only rendered
 * when a connection exists so this guard is a safety net.
 *
 * WHY no refetchInterval: sync errors are written once per sync run and never
 * updated (they accumulate). The user only needs to re-check if they've
 * triggered a new sync, which invalidates this query anyway.
 *
 * @param connectionId - the brokerage connection to fetch errors for
 */
export function useSyncErrors(connectionId: string) {
  const { accessToken } = useAuth();

  return useQuery({
    queryKey: ["sync-errors", connectionId],
    queryFn: () => createGateway(accessToken).getSyncErrors(connectionId),
    enabled: !!accessToken && connectionId.length > 0,
    // WHY staleTime 60s: errors don't change until the next sync. Caching
    // avoids repeated fetches when the banner re-mounts on tab switch.
    staleTime: 60_000,
  });
}

// ── Mutation hooks ────────────────────────────────────────────────────────────

/**
 * useInitiateBrokerageConnection — trigger the SnapTrade OAuth flow for a portfolio.
 *
 * On success the caller receives { connection_id, redirect_uri } and should
 * immediately set window.location.href = redirect_uri to send the user to the
 * SnapTrade portal. The connection starts in "pending" status; it becomes
 * "active" after the callback page calls activateBrokerageConnection().
 *
 * WHY not invalidate on success: the connection is still "pending" immediately
 * after initiation — the user hasn't completed the OAuth flow yet. We invalidate
 * the list after activation (in the callback page), not here.
 */
export function useInitiateBrokerageConnection() {
  const { accessToken } = useAuth();

  return useMutation({
    mutationFn: (portfolioId: string) =>
      createGateway(accessToken).initiateBrokerageConnection(portfolioId),
    // WHY no onSuccess invalidation: the connection is still pending; the list
    // doesn't meaningfully change until the user completes the OAuth flow.
    // ConnectBrokerageModal handles the redirect after the mutate succeeds.
    // WHY retry (CRIT-006 / FR-8.1): initiateBrokerageConnection is safe to retry
    // — a duplicate pending connection from a retry is benign (same portfolio).
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
  });
}

/**
 * useDisconnectBrokerageConnection — revoke a brokerage connection.
 *
 * WHY invalidate ALL brokerage-connections keys: a user may have the connection
 * list visible with or without a portfolioId filter. Invalidating with just
 * ["brokerage-connections"] as prefix (no second element) triggers a refetch
 * for ALL cached connection list queries simultaneously.
 */
export function useDisconnectBrokerageConnection() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (connectionId: string) =>
      createGateway(accessToken).disconnectBrokerageConnection(connectionId),
    // WHY retry (CRIT-006 / FR-8.1): disconnectBrokerageConnection is safe to retry
    // — S1 returns 404 on "already disconnected" (not 5xx); retry only fires on
    // transient network / 5xx failures.
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: () => {
      // WHY invalidate with partial key: queryClient.invalidateQueries with a
      // partial key prefix invalidates ALL queries whose key starts with
      // ["brokerage-connections"], regardless of the portfolioId segment.
      // This ensures both the portfolio tab view and any other views update.
      void queryClient.invalidateQueries({
        queryKey: ["brokerage-connections"],
      });
    },
  });
}

/**
 * useTriggerBrokerageSync — request an immediate re-sync for a connection.
 *
 * WHY 3-second delay before invalidation: the sync is asynchronous — S1 queues
 * a worker task that may take 2-5 seconds to start executing. If we invalidate
 * immediately, the refetch will see the old status. A 3-second delay gives the
 * worker time to pick up the task and update the connection status before we
 * refresh the UI. This is a UX heuristic, not a guarantee.
 */
export function useTriggerBrokerageSync() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (connectionId: string) =>
      createGateway(accessToken).triggerBrokerageSync(connectionId),
    // WHY retry (CRIT-006 / FR-8.1): POST /v1/brokerage-connections/{id}/sync
    // is 202-async and retry-safe by design (W1-Backend audit).
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: () => {
      // WHY setTimeout: give the async sync worker ~3s to pick up the task
      // before we refetch, so the user sees an updated status immediately.
      setTimeout(() => {
        void queryClient.invalidateQueries({
          queryKey: ["brokerage-connections"],
        });
        // Also invalidate sync errors — a fresh sync may clear or add errors
        void queryClient.invalidateQueries({
          queryKey: ["sync-errors"],
        });
      }, 3_000);
    },
  });
}
