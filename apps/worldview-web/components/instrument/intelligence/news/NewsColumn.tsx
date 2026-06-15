/**
 * components/instrument/intelligence/news/NewsColumn.tsx — T-D-02
 *
 * WHY: Left rail of Intelligence tab (30%). Infinite-scroll list of
 * CompactArticleRow plus a NewsFilters strip.
 * WHY useInfiniteQuery + IntersectionObserver: 30+ items visible; sentinel
 * pattern (see components/docs/DocsTableOfContents.tsx) converts paging
 * into pure scrolling.
 * WHY filter state lives here: state changes the query key → refetch.
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { Newspaper } from "lucide-react";
import { useEntityNewsInfinite } from "@/components/instrument/hooks/useEntityNewsInfinite";
// Round-3 consolidation (DS §15.12): the shared primitive replaced the local
// components/instrument/shared/EmptyState.tsx — copy now resolves through the
// reserved "instrument.no-articles" key in lib/copy/empty-states.ts.
import { EmptyState } from "@/components/primitives/EmptyState";
import { CompactArticleRow } from "./CompactArticleRow";
import { NewsFilters, type NewsSentiment, type NewsTimeRange } from "./NewsFilters";

interface NewsColumnProps {
  entityId: string;
}

export function NewsColumn({ entityId }: NewsColumnProps) {
  const [timeRange, setTimeRange] = useState<NewsTimeRange>("all");
  const [sentiment, setSentiment] = useState<NewsSentiment>(null);

  // Filters flow into the hook so the query key changes when they do.
  // Round-4 hardening (item 1b): isError/refetch consumed — a failed news
  // fetch previously rendered the "no articles" empty state (data undefined →
  // articles []), telling the analyst "no coverage exists" when the truth was
  // "the request failed". Errors and emptiness are different states.
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError, refetch } =
    useEntityNewsInfinite(entityId, {
      sentiment: sentiment ?? undefined,
      timeRange,
    });

  // Flatten paginated pages for render.
  const allArticles = data?.pages.flatMap((p) => p.articles) ?? [];

  // ── Sentiment filter (CLIENT-SIDE — BUG FIX 2026-06-15) ──────────────────
  // WHY client-side: S6's entity-articles endpoint has NO sentiment query
  // param (only start_date/end_date/order_by/limit/offset). But every
  // RankedArticle carries a categorical `sentiment` field, so we can narrow
  // the already-fetched feed locally. Previously the sentiment pills changed
  // the query key (forcing a refetch) but the refetch returned the SAME rows
  // — the pills were a visual no-op. Now they actually hide non-matching rows.
  //
  // NOTE the time-range filter is handled UPSTREAM (useEntityNewsInfinite maps
  // it to start_date, a real backend narrowing); only sentiment is local.
  const articles =
    sentiment == null
      ? allArticles
      : allArticles.filter((a) => a.sentiment === sentiment);

  // IntersectionObserver sentinel — fires when the bottom enters view.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
        }
      },
      // threshold 0.1: fire while still scrolling, masking latency.
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const filterStrip = (
    <NewsFilters
      timeRange={timeRange}
      onTimeRangeChange={setTimeRange}
      sentiment={sentiment}
      onSentimentChange={setSentiment}
    />
  );

  // Skeleton at 28px row height keeps layout stable while fetching.
  // Round-4 item 4: STATIC bars per DS §6.2 — raw animate-pulse is banned for
  // skeletons. data-testid lets tests target "loading" without coupling to
  // the (now animation-free) class list.
  if (isLoading) {
    return (
      <div className="flex flex-col h-full">
        {filterStrip}
        <div className="flex-1 overflow-y-auto" aria-busy="true">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} data-testid="news-skeleton-row" aria-hidden className="h-7 mx-3 my-1 rounded-sm bg-muted/20" />
          ))}
        </div>
      </div>
    );
  }

  // ── Per-section error (Round-4 hardening, item 1b) ─────────────────────────
  // NAMED error + Retry, scoped to this column only — the graph and context
  // rail keep working. WHY isError && !data: if any page already loaded, the
  // stale list stays visible (stale articles beat an error screen); this
  // branch only covers the cold fetch failing outright.
  if (isError && !data) {
    return (
      <div className="flex flex-col h-full">
        {filterStrip}
        <div
          data-testid="news-fetch-error"
          className="flex flex-1 flex-col items-center justify-center gap-1 px-3 text-center"
        >
          <p className="text-[12px] text-foreground">Couldn&apos;t load news</p>
          <p className="text-[11px] text-muted-foreground">
            The article feed failed to load — the graph and context rail are unaffected.
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-1 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {filterStrip}
      <div className="flex-1 overflow-y-auto">
        {articles.length === 0 ? (
          // Round-1 requirement 4: NAMED empty state (icon + headline) — a
          // bare sentence reads like a failed fetch; this reads like a state.
          // Round-3 consolidation: copy comes from the registry key; the
          // registry must stay STATIC (DS §15.12), so the old filter-aware
          // hint became a filter-aware ACTION — when a sentiment/time filter
          // is active the most likely cause is the filter, and a one-click
          // "Clear filters" reset is strictly more useful than a hint asking
          // the user to do the same thing manually.
          <EmptyState
            condition="empty-no-data"
            copyKey="instrument.no-articles"
            icon={Newspaper}
            action={
              sentiment != null || timeRange !== "all" ? (
                <button
                  type="button"
                  onClick={() => {
                    setSentiment(null);
                    setTimeRange("all");
                  }}
                  // 9px mono uppercase — same register as the other inline
                  // text-actions on this surface (ContradictionsBlock "Show
                  // all", RelatedEntitiesPanel "+N more"). focus-visible ring
                  // per the Round-3 keyboard-reachability pass.
                  className="font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
                >
                  Clear filters
                </button>
              ) : undefined
            }
          />
        ) : (
          <>
            {articles.map((a) => (
              <CompactArticleRow key={a.article_id} article={a} />
            ))}
            {/* Sentinel: invisible row watched by the observer above. */}
            <div ref={sentinelRef} className="h-4" aria-hidden="true" />
            {isFetchingNextPage && (
              <div className="text-[10px] text-muted-foreground text-center py-2">
                Loading more...
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
