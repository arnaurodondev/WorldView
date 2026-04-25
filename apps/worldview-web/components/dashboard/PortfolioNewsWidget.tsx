/**
 * components/dashboard/PortfolioNewsWidget.tsx — Top ranked news articles
 *
 * WHY THIS EXISTS: The dashboard morning routine includes a quick news scan.
 * Showing the 4 highest-relevance articles from the S6 ranked news endpoint
 * gives the trader immediate awareness of market-moving news before navigating
 * to the full Alerts & News page.
 *
 * WHY TOP 4 ONLY: col-span-3 is compact — 4 rows at h-[22px] plus header and
 * footer fits cleanly in the Row 4 slot without overflow.
 *
 * WHY ROUTING_TIER BADGE: The tier (LIGHT/STANDARD/HIGH, mapped from DEEP) tells
 * traders at a glance how significant the S6 pipeline ranked the article —
 * no need to parse a score number.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: S9 GET /v1/news/top via createGateway().getTopNews({ limit: 10 })
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery and useAuth.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatRelativeTime } from "@/lib/utils";
import type { RankedArticle } from "@/types/api";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PortfolioNewsWidget — top 4 ranked articles from the S6 intelligence pipeline.
 */
export function PortfolioNewsWidget() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-portfolio-news"],
    queryFn: () => createGateway(accessToken).getTopNews({ limit: 10 }),
    enabled: !!accessToken,
    // WHY 60_000: news feed refreshes frequently; 1-min stale time ensures we
    // catch breaking stories while not hammering S9.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const articles = (data?.articles ?? []).slice(0, 4);

  return (
    <div className="flex h-full flex-col bg-card">

      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PORTFOLIO NEWS
        </span>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
              <Skeleton className="h-3 w-[30px]" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-[24px]" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error / empty state ────────────────────────────────────────────── */}
      {isError && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No recent news" />
        </div>
      )}

      {!isLoading && !isError && articles.length === 0 && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No recent news" />
        </div>
      )}

      {/* ── Article rows ───────────────────────────────────────────────────── */}
      {!isLoading && !isError && articles.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {articles.map((article) => (
            <ArticleRow key={article.article_id} article={article} />
          ))}
        </div>
      )}

    </div>
  );
}

// ── ArticleRow sub-component ──────────────────────────────────────────────────

/**
 * ArticleRow — single article entry: tier badge + title + relative time.
 * WHY no link in dashboard row: clicking would leave the dashboard; the full
 * Alerts & News page handles article navigation. Dashboard rows are read-only.
 */
function ArticleRow({ article }: { article: RankedArticle }) {
  // ── Tier badge label ───────────────────────────────────────────────────────
  // WHY map tier: S6 returns LIGHT/MEDIUM/DEEP; dashboard shows L/M/H abbreviations
  // to fit in the compact h-[22px] row without overflow.
  const tierLabel = (() => {
    switch (article.routing_tier?.toUpperCase()) {
      case "DEEP":
      case "HIGH":
        return "H";
      case "MEDIUM":
        return "M";
      case "LIGHT":
        return "L";
      default:
        return "M";
    }
  })();

  const publishedAt = article.published_at
    ? formatRelativeTime(article.published_at)
    : "—";

  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows
    <div className="flex h-[22px] items-center gap-1.5 px-2">

      {/* Tier badge — abbreviated to fit compact row */}
      {/* WHY rounded-[2px]: design system mandates 2px radius everywhere */}
      <span className="shrink-0 rounded-[2px] bg-muted/40 px-1 font-mono text-[9px] text-muted-foreground">
        {tierLabel}
      </span>

      {/* Article title — truncated to single line */}
      <span
        className="flex-1 truncate text-[11px] text-foreground"
        title={article.title ?? ""}
      >
        {article.title ?? "Untitled"}
      </span>

      {/* Relative time — right-aligned, font-mono per §0 rules */}
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
        {publishedAt}
      </span>

    </div>
  );
}
