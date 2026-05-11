/**
 * components/instrument/FundamentalsTopNews.tsx — Compact 3-article news panel
 *
 * WHY THIS EXISTS: The Fundamentals right sidebar needs a news context panel.
 * Ratio analysis is backward-looking; news tells the analyst what's changing
 * right now that might invalidate the historical ratios. A 3-article compact
 * panel is enough to surface the current narrative without scrolling.
 *
 * WHY 3 ARTICLES (not more): The right sidebar is 280px with other panels above.
 * 3 × 22px rows = 66px + header + "More news" link = ~100px total. More articles
 * would push the panel below the fold. 3 articles surface the key story quickly.
 *
 * WHY NO TIER BADGE: Unlike InstrumentTopNews.tsx (which shows routing tier),
 * this compact panel omits the badge to save horizontal space in the 280px column.
 * Title and relative time are the primary signals; the full News tab has badges.
 *
 * WHY order_by=display_relevance_score: We want the most relevant articles, not
 * just the most recent. display_relevance_score is S6's composite signal that
 * weights market impact + LLM relevance + routing tier (PRD-0026).
 *
 * WHO USES IT: FundamentalsTab right sidebar (Wave D-2)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/articles?limit=3
 * DESIGN REFERENCE: PLAN-0041 §T-D-2-05
 */

"use client";
// WHY "use client": uses useQuery for news fetch.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundamentalsTopNewsProps {
  entityId: string;
  /** Callback to switch parent to the News tab */
  onViewAllNews?: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FundamentalsTopNews({ entityId, onViewAllNews }: FundamentalsTopNewsProps) {
  const { accessToken } = useAuth();

  // ── Fetch top 3 articles ──────────────────────────────────────────────────
  // WHY staleTime 120_000: news relevance changes quickly; 2-minute window is
  // short enough to surface breaking news but long enough to avoid hammering S6.
  const { data, isLoading } = useQuery({
    queryKey: ["entity-news-sidebar", entityId],
    queryFn: () =>
      createGateway(accessToken).getEntityNews(entityId, {
        limit: 3,
        order_by: "display_relevance_score",
      }),
    enabled: !!accessToken && !!entityId,
    staleTime: 120_000,
  });

  const articles = data?.articles ?? [];

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOP NEWS
        </span>
      </div>

      {/* ── Loading state ──────────────────────────────────────────────── */}
      {isLoading && (
        <>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center justify-between h-[22px] px-2 border-b border-border/30 gap-2">
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-8 flex-none" />
            </div>
          ))}
        </>
      )}

      {/* ── Empty state ────────────────────────────────────────────────── */}
      {!isLoading && articles.length === 0 && (
        <div className="px-2 py-1.5 text-[10px] font-mono text-muted-foreground">
          No recent news
        </div>
      )}

      {/* ── Article rows ─────────────────────────────────────────────────
          WHY h-[22px] row: matches §0.1 terminal data row height.
          WHY overflow-hidden on container: ensures truncate works within
          the fixed 280px column. */}
      {!isLoading &&
        articles.map((article) => (
          <a
            key={article.article_id}
            href={article.url ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between h-[22px] px-2 border-b border-border/30 gap-2 hover:bg-muted/50 transition-colors group"
          >
            {/* Title — truncated to available width */}
            <span className="font-mono text-[10px] text-foreground truncate flex-1 group-hover:text-primary transition-colors">
              {article.title ?? "Untitled"}
            </span>

            {/* Relative time — right-aligned, always visible */}
            {/* WHY text-muted-foreground/60: time is subordinate to title in scanability */}
            <span className="font-mono text-[9px] text-muted-foreground/60 flex-none whitespace-nowrap">
              {article.published_at ? formatRelativeTime(article.published_at) : "—"}
            </span>
          </a>
        ))}

      {/* ── More news link ───────────────────────────────────────────────
          WHY always show even with articles: encourages switching to News tab
          which has full pagination, filters, and tier badges. */}
      <button
        onClick={onViewAllNews}
        className="flex items-center gap-1 px-2 h-7 w-full text-[10px] font-mono text-muted-foreground hover:text-primary transition-colors border-t border-border/30"
      >
        <span>→ More news</span>
      </button>
    </div>
  );
}
