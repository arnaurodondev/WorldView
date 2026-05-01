/**
 * hooks/useBetaEnrollment.ts — read + mutate the user's beta-program row.
 *
 * WHY THIS EXISTS (PLAN-0052 Wave E T-E-5-07):
 * The /settings/beta-program page needs both a current-state read and a
 * single PATCH to flip the toggle. Co-locating both in this file mirrors
 * the useFeatureRequests pattern (read + write together so invalidation
 * is local and the mutation hook can target the exact queryKey).
 *
 * INVALIDATION SHAPE: On a successful PATCH we reset the cache directly
 * with the response body — the server returns the canonical row, so we
 * skip a follow-up GET. We still invalidate the same key for any other
 * subscribers (e.g. a header badge that surfaces beta-tester status).
 *
 * WHY a single shared queryKey ("beta-enrollment"): there's only one row
 * per user, no filters. A scalar key avoids the tuple cache-fragmentation
 * issue we'd hit if filters were ever added later.
 */

"use client";
// WHY "use client": uses useAuth (React context) + TanStack hooks — both
// require the React runtime.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
import type { BetaEnrollment, BetaEnrollmentPatch } from "@/types/api";

/**
 * useBetaEnrollment — fetches the current user's beta row.
 *
 * Returns the standard TanStack `useQuery` result. The hook is gated by
 * authentication: when the user is signed-out, we skip the network call
 * (the backend returns 401, which would surface as a useless error).
 * Components should render their own "sign in to opt in" placeholder when
 * `isAuthenticated` is false.
 */
export function useBetaEnrollment() {
  const { accessToken, isAuthenticated } = useAuth();

  return useQuery<BetaEnrollment>({
    queryKey: qk.feedback.betaEnrollment(),
    queryFn: () => createGateway(accessToken).getBetaEnrollment(),
    // WHY enabled gate: skips the call entirely when there's no token —
    // the backend would 401 and TanStack would surface a confusing error
    // banner. We let the page render an unauth empty-state instead.
    enabled: isAuthenticated,
    // 30s staleTime — the toggle isn't changing constantly so we cache
    // generously to avoid a refetch on every settings tab focus.
    staleTime: 30_000,
  });
}

/**
 * usePatchBetaEnrollment — flip the toggle / update notes.
 *
 * WHY no optimistic update: the toggle is binary and the request is fast
 * (server returns the row in one round-trip). We surface the pending state
 * via `mutation.isPending` so the toggle disables briefly during the call.
 * If we had a cluster of independent fields we'd consider optimistic, but
 * the simplicity tradeoff favours the honest pending state here.
 */
export function usePatchBetaEnrollment() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation<BetaEnrollment, Error, BetaEnrollmentPatch>({
    mutationFn: (payload) => createGateway(accessToken).patchBetaEnrollment(payload),
    onSuccess: (row) => {
      // WHY setQueryData over invalidateQueries: server returns the
      // canonical row in the PATCH response. Writing it directly avoids a
      // follow-up GET and keeps the toggle in sync without a flicker.
      queryClient.setQueryData<BetaEnrollment>(qk.feedback.betaEnrollment(), row);
      // Still invalidate so any other subscriber (e.g. nav badge) refreshes.
      void queryClient.invalidateQueries({ queryKey: qk.feedback.betaEnrollment() });
    },
  });
}
