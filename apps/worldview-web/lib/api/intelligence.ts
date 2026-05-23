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
import { qk } from "@/lib/query/keys";
import { apiFetch } from "./_client";
import type {
  EntityIntelligencePublic,
  EntityPathsResponse,
  NarrativeHistoryPage,
  PathFilters,
} from "@/types/intelligence";
import type { SentimentTimeseriesResponse } from "@/types/api";

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
    queryKey: qk.kg.intelligence(entityId),
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
    queryKey: qk.kg.paths(entityId, filters),
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
    queryKey: qk.kg.narratives(entityId),
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

// ── useEntitySentimentTimeseries ──────────────────────────────────────────────

/**
 * useEntitySentimentTimeseries — daily sentiment aggregates for an entity.
 *
 * WHY this hook exists: the SENTI overlay chip in TAOverlayPanel (PLAN-0091 F-2)
 * overlays net_sentiment (positive_ratio − negative_ratio) as a right-axis series
 * on the OHLCV chart. Analysts can correlate news sentiment direction with price
 * moves to identify sentiment-driven inflection points — a core Bloomberg feature.
 *
 * WHY staleTime 3_600_000 (1h): sentiment aggregates are recomputed by S6 at most
 * once per pipeline cycle (~60 min). Re-fetching more often wastes S9 resources
 * without improving the signal. The TAOverlayPanel only shows the series when the
 * SENTI chip is active, so the cache stays warm even when the chart is hidden.
 *
 * WHY entityId can be null: the hook is mounted once the instrument page loads;
 * entityId comes from the instrument brief which resolves async. The `enabled`
 * guard prevents a `GET /undefined/sentiment-timeseries` request on first render.
 *
 * @param entityId - The entity UUID (null until brief resolves → no fetch)
 * @param days     - Look-back window in days (1-365, default 90)
 */
export function useEntitySentimentTimeseries(entityId: string | null, days = 90) {
  const token = useAccessToken();

  return useQuery<SentimentTimeseriesResponse>({
    // WHY entityId ?? "": useQuery requires a stable, non-optional queryKey.
    // The `enabled` guard below prevents any fetch when entityId is null, so
    // the "" fallback never reaches the queryFn — it's only there to satisfy
    // TypeScript's requirement that the key be defined at hook call time.
    queryKey: qk.kg.sentimentTimeseries(entityId ?? "", days),
    queryFn: () =>
      apiFetch<SentimentTimeseriesResponse>(
        // WHY encodeURIComponent: entityId is a UUID so this is defensive;
        // it prevents any injection if the ID format ever changes.
        // WHY entityId ?? "": the enabled guard above prevents any fetch when entityId
        // is null, so "" is never reached — but this avoids the non-null assertion (entityId!)
        // which would silently produce "null" in the URL if the enabled guard were ever removed.
        `/v1/entities/${encodeURIComponent(entityId ?? "")}/sentiment-timeseries?days=${days}`,
        { token: token ?? undefined },
      ),
    // 1h — matches S6 pipeline cycle (see module comment)
    staleTime: 3_600_000,
    // WHY both conditions: the endpoint requires auth (X-Internal-JWT) and the
    // entityId must be a real UUID — we guard both to avoid spurious 401/422.
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
    // WHY retry (CRIT-006 / FR-8.1): POST /v1/entities/{id}/narratives/generate
    // returns 202 Accepted (async job queue) — safe to retry on transient 5xx/
    // network failures. 429 Too Many Requests is handled in NarrativeCard's
    // onSuccess toast; retries won't fire on 4xx (TanStack default).
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: () => {
      // WHY invalidate intelligence: current_narrative will update ~30s after
      // the generation completes. Invalidating now triggers a refetch that will
      // pick up the new narrative as soon as S9 has it.
      void queryClient.invalidateQueries({
        queryKey: qk.kg.intelligence(entityId),
      });
      // WHY invalidate narratives: the new version will appear in history once
      // the job completes. Invalidating the infinite cache causes the timeline
      // to refetch from the start, showing the freshest version at the top.
      void queryClient.invalidateQueries({
        queryKey: qk.kg.narratives(entityId),
      });
    },
  });
}
