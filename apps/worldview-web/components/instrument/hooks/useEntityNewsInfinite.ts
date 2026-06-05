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

// WHY pageParam = number (not opaque cursor): S6 endpoint is offset/limit-based.
//   pageParam N → "skip N*PAGE_SIZE results, return PAGE_SIZE more". Numbers
//   are stable, devtools-friendly, and allPages.length is the next index.
// WHY getNextPageParam compares articles.length === PAGE_SIZE: a short page
//   means we've hit the end of the feed → return undefined to stop scrolling.
// WHY staleTime 5min: news refreshes often but we avoid jittery re-fetch.
// WHY filters live only in queryKey: EntityNewsParams does not yet accept
//   sentiment/timeRange — wiring them at the API level is a future change;
//   the cache identity already differentiates per-filter combinations.
export function useEntityNewsInfinite(
  entityId: string,
  filters: EntityNewsFilters = {},
) {
  const token = useAccessToken();
  return useInfiniteQuery({
    queryKey: qk.news.forEntity(entityId, filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      createGateway(token).getEntityNews(entityId, {
        limit: PAGE_SIZE,
        offset: (pageParam as number) * PAGE_SIZE,
      }),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.articles.length === PAGE_SIZE ? allPages.length : undefined,
    staleTime: 5 * 60 * 1000,
    enabled: !!entityId,
  });
}
