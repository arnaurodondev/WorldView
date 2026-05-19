/**
 * hooks/useFeatureRequests.ts — TanStack Query for the public roadmap.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-02):
 * The /feedback public board (T-G-7-06) and the FeedbackModal feature-tab
 * preview both list feature requests with the same filters. Sharing one
 * hook keeps the queryKey shape consistent, so a vote mutation can
 * invalidate one cache entry and both surfaces refresh.
 *
 * WHY a parallel `useVoteFeature` mutation exists in this file: votes
 * mutate the same row that getFeatureRequests returns. Co-locating both
 * the read + the write makes invalidation trivial — the mutation knows
 * exactly which queryKey to bust.
 */

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { FeatureRequest, FeatureRequestFilters } from "@/types/api";

// ── Query key ──────────────────────────────────────────────────────────────
//
// WHY tuple shape: TanStack matches keys structurally, so passing the
// filters object as the second tuple element gives us per-filter caches.
// `null` placeholder when no filters are passed keeps the array shape
// stable (avoids the empty-tuple == undefined gotcha).

function makeKey(filters: FeatureRequestFilters | undefined) {
  return ["feature-requests", filters ?? null] as const;
}

// ── Read hook ──────────────────────────────────────────────────────────────

export function useFeatureRequests(filters?: FeatureRequestFilters) {
  const { accessToken } = useAuth();

  return useQuery({
    queryKey: makeKey(filters),
    queryFn: () => createGateway(accessToken).getFeatureRequests(filters ?? {}),
    // WHY enabled true even without a token: anonymous viewing is allowed
    // (the gateway issues a system JWT for unauthenticated calls and the
    // backend returns has_voted=false). Voting still requires auth.
    staleTime: 30_000,
  });
}

// ── Mutation hook ──────────────────────────────────────────────────────────

/**
 * useVoteFeature — idempotent upvote mutation.
 *
 * WHY optimistic update: voting feels instant on every other site;
 * waiting for the round-trip looks broken. We optimistically bump
 * vote_count + flip has_voted, then reconcile with the server response.
 *
 * WHY rollback in onError: if the POST fails (network / 401), we restore
 * the snapshot so the UI doesn't show a phantom vote.
 */
export function useVoteFeature() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => createGateway(accessToken).voteFeature(id),
    // WHY retry (CRIT-006 / FR-8.1): voteFeature is an idempotent upvote —
    // second click is a no-op server-side (documented in gateway method).
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onMutate: async (id: string) => {
      // Cancel in-flight refetches so they don't overwrite our optimistic state.
      await queryClient.cancelQueries({ queryKey: ["feature-requests"] });
      // Snapshot all matching queries so we can roll back on error.
      const snapshots = queryClient.getQueriesData<{
        items: FeatureRequest[];
        total: number;
      }>({ queryKey: ["feature-requests"] });

      // Optimistically update every cached list — votes are global.
      for (const [key, data] of snapshots) {
        if (!data) continue;
        queryClient.setQueryData(key, {
          ...data,
          items: data.items.map((row) =>
            row.id === id
              ? {
                  ...row,
                  // WHY vote_count + (has_voted ? 0 : 1): re-clicking after
                  // having voted is a no-op (idempotent on the backend).
                  vote_count: row.has_voted ? row.vote_count : row.vote_count + 1,
                  has_voted: true,
                }
              : row,
          ),
        });
      }
      return { snapshots };
    },
    onError: (_err, _id, context) => {
      // Restore each snapshot — same shape as we read in onMutate.
      if (!context) return;
      for (const [key, data] of context.snapshots) {
        queryClient.setQueryData(key, data);
      }
    },
    onSettled: () => {
      // Sync with the server — picks up vote_count changes from other voters.
      void queryClient.invalidateQueries({ queryKey: ["feature-requests"] });
    },
  });
}
