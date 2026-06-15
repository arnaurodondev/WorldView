/**
 * useEntityNewsInfinite.ts
 * WHY THIS EXISTS: the Intelligence tab's NewsColumn is an infinite-scroll
 *   feed. useInfiniteQuery (TanStack) gives automatic page accumulation,
 *   hasNextPage signals, and per-page loading state for free.
 * WHO USES IT: components/instrument/intelligence/NewsColumn.tsx (wired to
 *   an IntersectionObserver sentinel that calls fetchNextPage()).
 * DATA SOURCE: GET /v1/news/entity/{id} — S6 NLP-pipeline ranked feed.
 * DESIGN REFERENCE: PRD-0088 News tab section, PLAN-0090 T-A-03.
 */

"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

// WHY [key: string]: unknown — qk.news.forEntity types params as
// Readonly<Record<string, unknown>>; this index signature makes
// EntityNewsFilters structurally assignable to that shape.
export interface EntityNewsFilters {
  sentiment?: string;
  timeRange?: string;
  [key: string]: unknown;
}

const PAGE_SIZE = 20;

// ── Time-range → start_date mapping (BUG FIX 2026-06-15) ────────────────────
// WHY this exists: the NewsFilters strip exposes ALL / TODAY / 3D / 1W tabs.
// Previously these flowed ONLY into the TanStack query KEY — the request
// itself always sent just {limit, offset}, so every "filtered" fetch hit the
// SAME S6 query and returned IDENTICAL data. The filter was a visual no-op.
//
// S6's GET /api/v1/entities/{id}/articles DOES support a `start_date` query
// param (verified live: start_date=<today> narrowed 50→23 articles). So the
// time-range filter is a real, backend-supported narrowing — we just have to
// translate the UI token into an ISO-8601 lower bound and actually send it.
//
// "all" → no bound (S6 then defaults to its own 30-day window, the widest the
// backend offers). The others subtract a fixed span from now.
const TIME_RANGE_TO_MS: Record<string, number | null> = {
  all: null,
  day: 24 * 60 * 60 * 1000,
  "3d": 3 * 24 * 60 * 60 * 1000,
  "1w": 7 * 24 * 60 * 60 * 1000,
};

/**
 * resolveStartDate — translate a NewsTimeRange token into an ISO-8601
 * `start_date` (or undefined for "all"). Exported for unit testing the mapping
 * in isolation from the network layer.
 */
export function resolveStartDate(timeRange: string | undefined): string | undefined {
  const span = TIME_RANGE_TO_MS[timeRange ?? "all"] ?? null;
  if (span === null) return undefined;
  // WHY new Date(Date.now() - span): a relative lower bound anchored at the
  // current instant. ISO-8601 UTC ("...Z") is exactly what S6's `start_date`
  // Query param parses (datetime | None).
  return new Date(Date.now() - span).toISOString();
}

// WHY pageParam = number (not opaque cursor): S6 endpoint is offset/limit-based.
//   pageParam N → "skip N*PAGE_SIZE results, return PAGE_SIZE more". Numbers
//   are stable, devtools-friendly, and allPages.length is the next index.
// WHY getNextPageParam compares articles.length === PAGE_SIZE: a short page
//   means we've hit the end of the feed → return undefined to stop scrolling.
// WHY staleTime 5min: news refreshes often but we avoid jittery re-fetch.
//
// FILTER THREADING (BUG FIX 2026-06-15):
//   - timeRange → start_date query param (S6-supported, real narrowing).
//   - sentiment → S6 has NO sentiment param, but every RankedArticle carries a
//     `sentiment` field, so we filter CLIENT-SIDE in the consuming column
//     (NewsColumn) after the pages flatten. We surface the active sentiment in
//     the query key here so the cache slot stays distinct per filter combo
//     (no stale cross-filter bleed), even though the request body is identical
//     across sentiments. The actual row hiding happens in NewsColumn.
export function useEntityNewsInfinite(
  entityId: string,
  filters: EntityNewsFilters = {},
) {
  const token = useAccessToken();
  // Resolve the time-range token once per render into the wire param.
  const startDate = resolveStartDate(
    typeof filters.timeRange === "string" ? filters.timeRange : undefined,
  );
  return useInfiniteQuery({
    queryKey: qk.news.forEntity(entityId, filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      createGateway(token).getEntityNews(entityId, {
        limit: PAGE_SIZE,
        offset: (pageParam as number) * PAGE_SIZE,
        // BUG FIX: actually forward the resolved lower bound so the time-range
        // tabs narrow the feed instead of being decorative.
        start_date: startDate,
      }),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.articles.length === PAGE_SIZE ? allPages.length : undefined,
    staleTime: 5 * 60 * 1000,
    enabled: !!entityId,
  });
}
