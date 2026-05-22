/**
 * components/instrument/intelligence/news/NewsColumn.tsx — W7 T-05 / T-17
 *
 * WHY: Left rail of Intelligence tab. Infinite-scroll list of DenseArticleRow
 * (18px) plus a NewsFilters strip and j/k/Enter keyboard navigation.
 * WHY useInfiniteQuery + IntersectionObserver: 30+ items above the fold;
 * sentinel pattern converts paging into pure scrolling.
 * WHY j/k/Enter hotkeys (T-17): analysts with Bloomberg muscle memory expect
 * arrow-key-style navigation through news without touching the mouse.
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useEntityNewsInfinite } from "@/components/instrument/hooks/useEntityNewsInfinite";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { DenseArticleRow } from "./DenseArticleRow";
import { NewsFilters, type NewsSentiment, type NewsTimeRange } from "./NewsFilters";

interface NewsColumnProps {
  // PRD-0089 F2 §6.5: this rail is tradable-only, so the canonical id name
  // is `instrumentId`. Post-F2 `instrument_id === entity_id` for tradable
  // kinds, so the parent (IntelligenceTab) can hand its entityId straight in.
  instrumentId: string;
}

export function NewsColumn({ instrumentId }: NewsColumnProps) {
  const [timeRange, setTimeRange] = useState<NewsTimeRange>("all");
  const [sentiment, setSentiment] = useState<NewsSentiment>(null);
  // WHY selectedIdx (not a Set): single selection — arrow keys move a cursor.
  const [selectedIdx, setSelectedIdx] = useState<number>(-1);

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useEntityNewsInfinite(instrumentId, {
      sentiment: sentiment ?? undefined,
      timeRange,
    });

  const articles = data?.pages.flatMap((p) => p.articles) ?? [];

  // ── j/k/Enter hotkeys ─────────────────────────────────────────────────────
  const { registry } = useHotkeyScope();

  // WHY useCallback on handlers: registry.register stores a reference;
  // stable refs prevent repeated unregister/register on each render.
  const moveDown = useCallback(
    (e: KeyboardEvent) => {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, articles.length - 1));
    },
    [articles.length],
  );

  const moveUp = useCallback((e: KeyboardEvent) => {
    e.preventDefault();
    setSelectedIdx((i) => Math.max(i - 1, 0));
  }, []);

  const openSelected = useCallback(
    (e: KeyboardEvent) => {
      e.preventDefault();
      const article = articles[selectedIdx];
      if (!article?.url) return;
      console.debug("[intelligence] news.open", { idx: selectedIdx, url: article.url });
      window.open(article.url, "_blank", "noopener,noreferrer");
    },
    [articles, selectedIdx],
  );

  useEffect(() => {
    const unJ = registry.register({
      id: "intelligence.news.j",
      chord: "j",
      scope: "page",
      group: "Navigation",
      label: "Next article",
      handler: moveDown,
    });
    const unK = registry.register({
      id: "intelligence.news.k",
      chord: "k",
      scope: "page",
      group: "Navigation",
      label: "Previous article",
      handler: moveUp,
    });
    const unEnter = registry.register({
      id: "intelligence.news.enter",
      chord: "enter",
      scope: "page",
      group: "Action",
      label: "Open selected article",
      handler: openSelected,
    });
    return () => {
      unJ();
      unK();
      unEnter();
    };
  }, [registry, moveDown, moveUp, openSelected]);

  // Reset selection when articles reload (filter change).
  useEffect(() => {
    setSelectedIdx(-1);
  }, [instrumentId, timeRange, sentiment]);

  // ── IntersectionObserver sentinel ─────────────────────────────────────────
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

  if (isLoading) {
    return (
      <div className="flex flex-col h-full">
        {filterStrip}
        <div className="flex-1 overflow-y-auto">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-[18px] mx-3 my-0.5 bg-muted/20 animate-pulse" />
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
            {articles.map((a, idx) => (
              <DenseArticleRow
                key={a.article_id}
                article={a}
                highlighted={idx === selectedIdx}
              />
            ))}
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
