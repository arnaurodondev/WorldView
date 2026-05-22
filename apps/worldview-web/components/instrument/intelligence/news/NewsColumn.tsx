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
import { useEntityNewsInfinite } from "@/components/instrument/hooks/useEntityNewsInfinite";
import { DenseArticleRow } from "./DenseArticleRow";
import { NewsFilters, type NewsSentiment, type NewsTimeRange } from "./NewsFilters";

interface NewsColumnProps {
  // PRD-0089 F2 §6.5: this rail is tradable-only, so the canonical id name
  // is `instrumentId`. Post-F2 `instrument_id === entity_id` for tradable
  // kinds, so the parent (cross-kind IntelligenceTab) can hand its
  // `entityId` value straight in.
  instrumentId: string;
}

export function NewsColumn({ instrumentId }: NewsColumnProps) {
  const [timeRange, setTimeRange] = useState<NewsTimeRange>("all");
  const [sentiment, setSentiment] = useState<NewsSentiment>(null);

  // Filters flow into the hook so the query key changes when they do.
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useEntityNewsInfinite(instrumentId, {
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
            <div key={i} className="h-7 mx-3 my-1 bg-muted/20 animate-pulse" />
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
          <div className="text-[11px] text-muted-foreground text-center py-8">
            No articles for this entity.
          </div>
        ) : (
          <>
            {articles.map((a) => (
              <DenseArticleRow key={a.article_id} article={a} />
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
