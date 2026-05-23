/**
 * components/instrument/intelligence/news/NewsColumn.tsx — W7 T-05 / T-17
 *
 * WHY: Left rail of Intelligence tab. Infinite-scroll list of DenseArticleRow
 * (18px) plus a NewsFilters strip and j/k/Enter keyboard navigation.
 * WHY useInfiniteQuery + IntersectionObserver: 30+ items above the fold;
 * sentinel pattern converts paging into pure scrolling.
 * WHY j/k/Enter hotkeys (T-17): analysts with Bloomberg muscle memory expect
 * arrow-key-style navigation through news without touching the mouse.
 *
 * PLAN-0091 C-2: SentimentBadge and ArticleImpactDrawer are wired inside
 * DenseArticleRow (after the source code column). This column passes the
 * full RankedArticle down, so article.sentiment and article.article_id are
 * available to the row without any prop threading here.
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useEntityNewsInfinite } from "@/components/instrument/hooks/useEntityNewsInfinite";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { DenseArticleRow } from "./DenseArticleRow";
import { NewsFilters, type NewsSentiment, type NewsTimeRange } from "./NewsFilters";
// PLAN-0091 C-2: SentimentBadge + ArticleImpactDrawer wired at the column level
// so DenseArticleRow stays a pure presentational component with no query hooks.
// WHY here (not inside DenseArticleRow): DenseArticleRow has existing tests that
// render without <ApiClientProvider>. Adding ArticleImpactDrawer (which calls
// useAuthedQuery) inside DenseArticleRow would require mocking the provider in
// every DenseArticleRow test. Wiring in NewsColumn avoids that test surface
// growth while still placing the badges visually inline with each row.
import { SentimentBadge } from "@/components/ui/sentiment-badge";
import { ArticleImpactDrawer } from "@/components/instrument/intelligence/ArticleImpactDrawer";

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
      // WHY protocol check: reject javascript:/data: URLs to prevent injection.
      try {
        const parsed = new URL(article.url);
        if (!["http:", "https:"].includes(parsed.protocol)) return;
      } catch {
        return;
      }
      console.debug("[intelligence] news.open", { idx: selectedIdx, article_id: article.article_id });
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
              // PLAN-0091 C-2: wrap each row in a flex container so the
              // SentimentBadge and ArticleImpactDrawer sit inline to the right
              // of the DenseArticleRow without disrupting its internal layout.
              // WHY relative (not absolute): the badges must occupy real space in
              // the row so their widths don't collapse onto the headline text.
              // WHY items-center: badges are smaller than 18px and need vertical
              // centering relative to the row div.
              <div
                key={a.article_id}
                className="flex items-center"
              >
                <DenseArticleRow
                  article={a}
                  highlighted={idx === selectedIdx}
                />
                {/*
                 * WHY only when article_id is defined: LIGHT-tier articles may
                 * arrive with a null article_id (pre-scoring state). Rendering
                 * ArticleImpactDrawer with a null id fires a guaranteed 404
                 * to /v1/articles/null/impact-history. Guard avoids the wasted request.
                 */}
                {a.article_id && (
                  <div className="flex items-center gap-1 shrink-0 ml-1">
                    <SentimentBadge sentiment={a.sentiment} />
                    <ArticleImpactDrawer articleId={a.article_id} />
                  </div>
                )}
              </div>
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
