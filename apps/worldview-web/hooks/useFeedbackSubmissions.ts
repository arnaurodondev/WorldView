/**
 * hooks/useFeedbackSubmissions.ts — admin-only submissions list query.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-02):
 * The /admin/feedback dashboard (T-G-7-07) needs the full tenant feedback
 * list with filters (status, kind, severity), virtualised pagination, and
 * a parallel PATCH mutation for triage actions (status/tags/assignee). The
 * end-user "My submissions" view passes mine=true to the same endpoint —
 * we expose both flows from this file so the admin/user split is obvious.
 *
 * SECURITY: The backend rejects non-admin callers when `mine` is absent
 * (returns 403). The admin dashboard hides itself behind a role check too,
 * but server-side validation is the actual guard.
 */

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type {
  FeedbackSubmission,
  FeedbackSubmissionFilters,
  FeedbackSubmissionUpdate,
} from "@/types/api";

// ── Query keys ─────────────────────────────────────────────────────────────

const ROOT_KEY = "feedback-submissions" as const;

function makeKey(filters: FeedbackSubmissionFilters | undefined) {
  return [ROOT_KEY, filters ?? null] as const;
}

// ── Read hook ──────────────────────────────────────────────────────────────

/**
 * useFeedbackSubmissions — list submissions matching the supplied filters.
 *
 * @param filters pass `mine: true` for the user-facing view (works without
 *   admin role); omit it (or pass `mine: false`) to fetch the admin list
 *   (server returns 403 if the JWT lacks role=admin).
 */
export function useFeedbackSubmissions(filters?: FeedbackSubmissionFilters) {
  const { accessToken } = useAuth();

  return useQuery({
    queryKey: makeKey(filters),
    queryFn: () =>
      createGateway(accessToken).getFeedbackSubmissions(filters ?? {}),
    enabled: !!accessToken,
    // WHY staleTime 15s: the admin triage UI is a "live" workflow — staff
    // expect status changes from another tab to appear quickly. 15s
    // balances perceived freshness with backend load.
    staleTime: 15_000,
  });
}

// ── Triage mutation ────────────────────────────────────────────────────────

interface PatchArgs {
  id: string;
  fields: FeedbackSubmissionUpdate;
}

/**
 * usePatchFeedbackSubmission — admin-only triage update.
 *
 * WHY optimistic patch: triage UX feels much snappier when the row updates
 * the moment the dropdown closes. We snapshot+rollback on error.
 */
export function usePatchFeedbackSubmission() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, fields }: PatchArgs) =>
      createGateway(accessToken).patchFeedbackSubmission(id, fields),
    // WHY retry (CRIT-006 / FR-8.1): PATCH patchFeedbackSubmission is idempotent
    // (applying the same status/tags/assignee twice is a no-op server-side).
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onMutate: async ({ id, fields }) => {
      await queryClient.cancelQueries({ queryKey: [ROOT_KEY] });
      const snapshots = queryClient.getQueriesData<{
        items: FeedbackSubmission[];
        total: number;
      }>({ queryKey: [ROOT_KEY] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        queryClient.setQueryData(key, {
          ...data,
          items: data.items.map((row) =>
            row.id === id
              ? {
                  ...row,
                  ...(fields.status !== undefined ? { status: fields.status } : {}),
                  ...(fields.tags !== undefined ? { tags: fields.tags } : {}),
                  ...(fields.assigned_to !== undefined
                    ? { assigned_to: fields.assigned_to }
                    : {}),
                }
              : row,
          ),
        });
      }
      return { snapshots };
    },
    onError: (_err, _vars, context) => {
      if (!context) return;
      for (const [key, data] of context.snapshots) {
        queryClient.setQueryData(key, data);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: [ROOT_KEY] });
    },
  });
}
