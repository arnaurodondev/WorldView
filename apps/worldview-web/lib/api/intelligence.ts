/**
 * lib/api/intelligence.ts — Intelligence page TanStack Query hooks (PLAN-0074 Wave H)
 *
 * WHY THIS EXISTS: Provides three hooks used by the intelligence page panels:
 *   - useEntityIntelligence: main summary (sidebar + health badge)
 *   - useEntityPaths: multi-hop path insights (paths tab)
 *   - useEntityNarrativeHistory: paginated narrative history (narrative tab)
 *   - useTriggerNarrativeGeneration: mutation to queue a new narrative
 *
 * DESIGN DECISIONS:
 *   - staleTime 60_000 for intelligence: health/confidence scores are re-computed
 *     every ~1 min by the KG pipeline. Shorter staleTime = unnecessary refetches;
 *     longer = stale scores visible while the pipeline is actively updating.
 *   - staleTime 300_000 for paths: path insights are expensive to compute (graph
 *     traversal + LLM scoring). They are cached for 5 min on the backend; there
 *     is no benefit to re-fetching more frequently than the backend cache.
 *   - useInfiniteQuery for narratives: narrative history grows over time; cursor
 *     pagination avoids page-shift bugs that affect offset pagination on live data.
 *
 * ALL CALLS go via /api/v1/... (R14: frontend → S9 only via Next.js rewrite).
 * Auth token is injected by useApiClient() / useAccessToken() at the hook level.
 *
 * DATA SOURCES (via S9 proxy):
 *   GET  /v1/entities/{id}/intelligence
 *   GET  /v1/entities/{id}/paths
 *   GET  /v1/entities/{id}/narratives
 *   POST /v1/entities/{id}/narratives/generate
 */

"use client";
// WHY "use client": TanStack Query hooks (useQuery, useInfiniteQuery, useMutation)
// use React state and context — browser-only. Server Components cannot use them.

import {
  useQuery,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useAccessToken } from "@/lib/api-client";
import { apiFetch } from "./_client";
import type {
  EntityIntelligencePublic,
  EntityPathsResponse,
  NarrativeHistoryPage,
  PathFilters,
} from "@/types/intelligence";

// ── Query key factory ─────────────────────────────────────────────────────────

/**
 * iqk — Intelligence query key factory.
 *
 * WHY a factory (not inline arrays): TanStack Query's cache key comparison uses
 * deep equality. By centralising key shapes here, invalidation in useTriggerNarrativeGeneration
 * uses the SAME shape as the query definition — impossible to miss an
 * element or get the order wrong in two places.
 */
const iqk = {
  /** Cache key for GET /v1/entities/{id}/intelligence */
  intelligence: (entityId: string) =>
    ["entity-intelligence", entityId] as const,
  /** Cache key for GET /v1/entities/{id}/paths */
  paths: (entityId: string, filters: PathFilters) =>
    ["entity-paths", entityId, filters] as const,
  /** Cache key for GET /v1/entities/{id}/narratives (infinite) */
  narratives: (entityId: string) =>
    ["entity-narratives", entityId] as const,
};

// ── useEntityIntelligence ─────────────────────────────────────────────────────

/**
 * useEntityIntelligence — fetches the intelligence summary for an entity.
 *
 * WHY staleTime 60_000 (1 min):
 * The KG pipeline updates confidence/health scores roughly every minute.
 * A 1-min stale window means the sidebar health badge reflects the pipeline's
 * most recent computation without triggering excessive S9 load. Longer would
 * show stale data; shorter would hammer S9 on every re-focus.
 *
 * WHY enabled: !!entityId:
 * The hook is used inside a component that might render before the entityId
 * resolves (e.g., during a URL param read). Without this guard, the first render
 * fires GET /v1/entities/undefined/intelligence → 422 from S9 validation.
 *
 * @param entityId - The entity UUIDv7 to fetch intelligence for
 */
export function useEntityIntelligence(entityId: string) {
  const token = useAccessToken();

  return useQuery<EntityIntelligencePublic>({
    // WHY [entityId] in key: each entity gets its own cache slot. Switching
    // between entity pages (A → B → A) reuses A's cached data immediately.
    queryKey: iqk.intelligence(entityId),
    queryFn: () =>
      apiFetch<EntityIntelligencePublic>(
        `/v1/entities/${encodeURIComponent(entityId)}/intelligence`,
        { token: token ?? undefined },
      ),
    // 1 min — aligns with KG pipeline cycle (see module comment)
    staleTime: 60_000,
    // Only fire when we have a real entity ID AND a token
    enabled: !!entityId && !!token,
  });
}

// ── useEntityPaths ────────────────────────────────────────────────────────────

/**
 * useEntityPaths — fetches multi-hop path insights for an entity.
 *
 * WHY staleTime 300_000 (5 min):
 * Path computation is expensive (graph traversal + LLM scoring). S9 caches
 * results for 5 min on the backend. Re-fetching faster than the backend cache
 * TTL would always return the same stale data anyway — no value in doing it.
 *
 * WHY filters in the query key:
 * The user can change filters (minScore, hop range) in the Paths tab. Each
 * unique filter combination gets its own TanStack cache slot so switching
 * filters shows the correct data instantly from cache (if previously fetched).
 *
 * @param entityId - The entity UUIDv7
 * @param filters  - Optional filter params (limit, minScore, minHops, maxHops)
 */
export function useEntityPaths(entityId: string, filters: PathFilters = {}) {
  const token = useAccessToken();

  return useQuery<EntityPathsResponse>({
    // WHY filters in key: see module comment on filter-keying
    queryKey: iqk.paths(entityId, filters),
    queryFn: () => {
      // Build query params from filters — only add defined values
      const params = new URLSearchParams();
      if (filters.limit !== undefined) params.set("limit", String(filters.limit));
      if (filters.minScore !== undefined) params.set("min_score", String(filters.minScore));
      if (filters.minHops !== undefined) params.set("min_hops", String(filters.minHops));
      if (filters.maxHops !== undefined) params.set("max_hops", String(filters.maxHops));
      const qs = params.toString();
      return apiFetch<EntityPathsResponse>(
        `/v1/entities/${encodeURIComponent(entityId)}/paths${qs ? `?${qs}` : ""}`,
        { token: token ?? undefined },
      );
    },
    // 5 min — matches backend cache TTL for path computation (see module comment)
    staleTime: 300_000,
    enabled: !!entityId && !!token,
  });
}

// ── useEntityNarrativeHistory ─────────────────────────────────────────────────

/**
 * useEntityNarrativeHistory — paginated narrative version history.
 *
 * WHY useInfiniteQuery (not useQuery):
 * Narrative history grows over time and can have 100+ versions for active
 * entities. Loading all at once is wasteful. Infinite scroll loads the next
 * page only when the user scrolls to the bottom of the timeline.
 *
 * WHY cursor pagination (not page numbers):
 * Narratives are generated at runtime. If a new version is generated between
 * page 1 and page 2 being fetched, offset-based pagination would skip or
 * duplicate a version. Cursor pagination anchors to a specific version_id,
 * giving a stable sequence regardless of concurrent inserts.
 *
 * @param entityId - The entity UUIDv7
 */
export function useEntityNarrativeHistory(entityId: string) {
  const token = useAccessToken();

  return useInfiniteQuery<NarrativeHistoryPage>({
    queryKey: iqk.narratives(entityId),
    // WHY pageParam as the cursor:
    // TanStack Query passes the return value of `getNextPageParam` as `pageParam`
    // on the next fetch. We pass it as `cursor=` to the API. On the first fetch
    // pageParam is undefined (no cursor = start from most recent).
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (pageParam) params.set("cursor", pageParam as string);
      return apiFetch<NarrativeHistoryPage>(
        `/v1/entities/${encodeURIComponent(entityId)}/narratives?${params.toString()}`,
        { token: token ?? undefined },
      );
    },
    // WHY null initialPageParam: first fetch has no cursor (start from newest)
    initialPageParam: null as string | null,
    // WHY extract next_cursor: TanStack passes this return value as `pageParam`
    // for the NEXT fetch. Returning undefined stops the infinite scroll.
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: !!entityId && !!token,
  });
}

// ── useTriggerNarrativeGeneration ─────────────────────────────────────────────

/**
 * useTriggerNarrativeGeneration — queues a new narrative generation for an entity.
 *
 * WHY useMutation (not useQuery):
 * POST requests with side effects (async job queuing) are mutations. They
 * are user-initiated, not automatic, and need loading/error/success states
 * separate from the data-fetching queries.
 *
 * WHY invalidate both intelligence AND narratives on success:
 * After a successful generation trigger (202), the backend will:
 *   1. Queue the job → eventually update `current_narrative` in the intelligence
 *      summary endpoint. Invalidating intelligence forces a refetch so the
 *      sidebar picks up the new narrative when it arrives.
 *   2. Create a new NarrativeVersionPublic → invalidating narratives clears
 *      the infinite scroll cache so the timeline shows the new version.
 *
 * RETURNS 202 Accepted (not 200 OK) — the job is queued asynchronously.
 * The caller should show "Queued" toast, then the narrative arrives in ~30s.
 *
 * @param entityId - The entity UUIDv7
 */
export function useTriggerNarrativeGeneration(entityId: string) {
  const token = useAccessToken();
  const queryClient = useQueryClient();

  return useMutation<void, Error>({
    mutationFn: async () => {
      await apiFetch<void>(
        `/v1/entities/${encodeURIComponent(entityId)}/narratives/generate`,
        {
          method: "POST",
          token: token ?? undefined,
        },
      );
    },
    onSuccess: () => {
      // WHY invalidate intelligence: current_narrative will update ~30s after
      // the generation completes. Invalidating now triggers a refetch that will
      // pick up the new narrative as soon as S9 has it.
      void queryClient.invalidateQueries({
        queryKey: iqk.intelligence(entityId),
      });
      // WHY invalidate narratives: the new version will appear in history once
      // the job completes. Invalidating the infinite cache causes the timeline
      // to refetch from the start, showing the freshest version at the top.
      void queryClient.invalidateQueries({
        queryKey: iqk.narratives(entityId),
      });
    },
  });
}
