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
import { EmptyState } from "@/components/instrument/shared/EmptyState";
import { CompactArticleRow } from "./CompactArticleRow";
import { NewsFilters, type NewsSentiment, type NewsTimeRange } from "./NewsFilters";

interface NewsColumnProps {
  entityId: string;
}

export function NewsColumn({ entityId }: NewsColumnProps) {
  const [timeRange, setTimeRange] = useState<NewsTimeRange>("all");
  const [sentiment, setSentiment] = useState<NewsSentiment>(null);

  // Filters flow into the hook so the query key changes when they do.
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useEntityNewsInfinite(entityId, {
      sentiment: sentiment ?? undefined,
      timeRange,
    });

  // Flatten paginated pages for render.
  const articles = data?.pages.flatMap((p) => p.articles) ?? [];

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
  if (isLoading) {
    return (
      <div className="flex flex-col h-full">
        {filterStrip}
        <div className="flex-1 overflow-y-auto">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-7 mx-3 my-1 rounded-sm bg-muted/20 animate-pulse" />
          ))}
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
          // WHY filter-aware hint: with an active sentiment/time filter the
          // most likely cause is the filter, not a pipeline gap.
          <EmptyState
            icon={Newspaper}
            headline="No articles for this entity"
            hint={
              sentiment != null || timeRange !== "all"
                ? "Try clearing the sentiment or time filters above."
                : "Articles appear here as the news pipeline links coverage to this entity."
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
