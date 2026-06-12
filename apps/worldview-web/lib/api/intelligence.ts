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
  useQueries,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useAccessToken } from "@/lib/api-client";
import { apiFetch, GatewayError } from "./_client";
// PLAN-0099 Wave 2: relation-detail + entity-events fetchers live in the KG
// api module (single owner of /v1/relations + /v1/entities URL building);
// these hooks only add TanStack cache policy on top.
import { createKnowledgeGraphApi } from "./knowledge-graph";
import type { RelationDetail, EntityEventsResponse } from "./knowledge-graph";
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
  /** Cache key for GET /v1/relations/{relation_id} (PLAN-0099 Wave 2) */
  relationDetail: (relationId: string) =>
    ["relation-detail", relationId] as const,
  /** Cache key for GET /v1/entities/{id}/events (PLAN-0099 Wave 2) */
  events: (entityId: string) =>
    ["entity-events", entityId] as const,
  /** Cache key for GET /v1/articles/{document_id} (QA Wave-3 closeout) */
  articleMeta: (documentId: string) =>
    ["evidence-article-meta", documentId] as const,
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

// ── useRelationDetail (PLAN-0099 Wave 2) ──────────────────────────────────────

/**
 * useRelationDetail — full edge dossier for the Intelligence tab's inspector.
 *
 * Fires GET /v1/relations/{relation_id}?evidence_limit=25 when an edge is
 * selected on the graph canvas (or via a top-relation row click).
 *
 * WHY staleTime 5 min: relation rows mutate only when the KG consumers process
 * new evidence (minutes-scale cadence). Re-fetching the same edge inside one
 * investigation session would return identical data — 5 min matches the graph
 * cache so the canvas and the inspector never show different confidence values
 * for longer than one graph refresh cycle.
 *
 * WHY enabled gate on relationId: the hook is mounted unconditionally by the
 * inspector panel (hooks cannot be conditional); when no edge is selected
 * relationId is null and the query stays idle.
 *
 * RETURNS data === null (not undefined) for a 404 — the relation was
 * re-canonicalised away after the graph snapshot. The inspector renders a
 * named "no longer available" state for that case.
 *
 * @param relationId GraphEdge.id (== KG relation_id), or null when idle.
 */
export function useRelationDetail(relationId: string | null) {
  const token = useAccessToken();

  return useQuery<RelationDetail | null>({
    queryKey: iqk.relationDetail(relationId ?? "none"),
    queryFn: () =>
      createKnowledgeGraphApi(token ?? undefined).getRelationDetail(relationId as string),
    staleTime: 5 * 60 * 1000,
    enabled: !!relationId && !!token,
    // WHY retry 1: a single retry covers transient S9/S7 blips. The evidence
    // list can be heavy (25 rows × chunk text) — hammering a failing backend
    // with the default 3 retries would triple the pain for zero gain.
    retry: 1,
  });
}

// ── useEvidenceArticleMetadata (QA Wave-3 closeout, 2026-06-11) ──────────────

/**
 * EvidenceArticleMetadata — the reshaped article metadata contract returned by
 * S9 GET /v1/articles/{document_id} (api-gateway routes/content.py, which
 * resolves pipeline doc_ids against content-store's documents/batch).
 */
export interface EvidenceArticleMetadata {
  document_id: string;
  title: string | null;
  url: string | null;
  /** Aliases content-store's source_name (see the S9 route docstring). */
  source: string | null;
  source_type: string | null;
  published_at: string | null;
  word_count: number | null;
}

/**
 * useEvidenceArticleMetadata — resolve evidence document_ids → article
 * title/url for the EdgeInspector's provenance lines.
 *
 * WHY THIS EXISTS: relation evidence rows (GET /v1/relations/{id}) carry only
 * document_id — intelligence_db has no article metadata (R9). The gateway
 * later added GET /v1/articles/{document_id} (content-store resolution), but
 * the Intelligence frontend predates that route and never called it, so the
 * inspector showed only source_name + date. RelationEvidenceItem already has
 * forward-compat `article_title`/`article_url` slots; this hook fills them
 * client-side.
 *
 * WHY useQueries (one query per doc id, not one batch query): evidence lists
 * repeat the same articles across edges of the same entity — per-document
 * cache keys mean a title fetched for edge A is reused instantly for edge B.
 * The inspector caps evidence at 25 rows, so worst case is 25 parallel GETs
 * once per session.
 *
 * WHY staleTime Infinity: an article's title/url never changes after ingest.
 *
 * WHY 404 → null (cached): tombstoned/unknown doc_ids are a NORMAL state —
 * the row keeps its source_name fallback, and we never refetch a known-missing
 * id.
 *
 * @param documentIds evidence document_ids (duplicates/nulls already removed
 *                    by the caller); order does not matter.
 * @returns Map document_id → metadata for every RESOLVED article. Unresolved
 *          (loading / 404 / error) ids are simply absent.
 */
export function useEvidenceArticleMetadata(
  documentIds: ReadonlyArray<string>,
): ReadonlyMap<string, EvidenceArticleMetadata> {
  const token = useAccessToken();
  // Stable, deduped ordering so the queries array (and thus the hook call
  // sequence) is identical across re-renders with the same input set.
  const unique = Array.from(new Set(documentIds)).sort();

  const results = useQueries({
    queries: unique.map((docId) => ({
      queryKey: iqk.articleMeta(docId),
      queryFn: async (): Promise<EvidenceArticleMetadata | null> => {
        try {
          return await apiFetch<EvidenceArticleMetadata>(
            `/v1/articles/${encodeURIComponent(docId)}`,
            { token: token ?? undefined },
          );
        } catch (err) {
          // 404 = content-store doesn't know the doc (tombstoned) — a named
          // empty state, not an error worth retrying or surfacing.
          if (err instanceof GatewayError && err.status === 404) return null;
          throw err;
        }
      },
      staleTime: Infinity,
      retry: 1,
      enabled: !!token,
    })),
  });

  // Plain construction (no useMemo): useQueries returns a fresh array each
  // render anyway, so memoising on it would never hit. Map building over ≤25
  // entries is trivially cheap.
  const map = new Map<string, EvidenceArticleMetadata>();
  results.forEach((r, i) => {
    if (r.data) map.set(unique[i], r.data);
  });
  return map;
}

// ── useEntityEvents (PLAN-0099 Wave 2) ────────────────────────────────────────

/**
 * useEntityEvents — entity-scoped temporal events for the EVENTS rail block.
 *
 * Fires GET /v1/entities/{id}/events?active_only=false&limit=20. The gateway
 * filters via entity_event_exposures and computes lifecycle_phase per event.
 *
 * WHY staleTime 5 min: temporal events are produced by Worker 13D batches —
 * they change at pipeline cadence (tens of minutes), not interactively.
 *
 * WHY activeOnly=false (investigation surface): residual/expired events are
 * still context the analyst needs ("there WAS a regulatory threat in May") —
 * the lifecycle chip on each row carries the phase signal.
 */
export function useEntityEvents(entityId: string) {
  const token = useAccessToken();

  return useQuery<EntityEventsResponse | null>({
    queryKey: iqk.events(entityId),
    queryFn: () =>
      createKnowledgeGraphApi(token ?? undefined).getEntityEvents(entityId, {
        activeOnly: false,
        limit: 20,
      }),
    staleTime: 5 * 60 * 1000,
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
