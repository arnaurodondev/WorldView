/**
 * components/workspace/WorkspaceNewsPanel.tsx — Compact top-news feed for workspace
 *
 * WHY THIS EXISTS: Traders monitoring the workspace need market-moving news without
 * navigating away. This panel fetches PRD-0026 ranked top-news and shows compact
 * rows (title + source + timestamp) — maximizing articles visible per panel pixel.
 *
 * WHY COMPACT ROWS (not ArticleCard): ArticleCard is designed for full-width article
 * pages with spacious padding. In a workspace panel (~400px), compact rows show
 * 10-12 articles where ArticleCard would show 2-3. Data density is the terminal mandate.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "news"
 * DATA SOURCE: GET /v1/news/top (S9 gateway, PRD-0026 composite scoring)
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel widgets, §0.2 22px row height
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only state management)

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatRelativeTime, safeExternalUrl } from "@/lib/utils";

export function WorkspaceNewsPanel() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["workspace-top-news"],
    queryFn: () => createGateway(accessToken).getTopNews({ limit: 15, offset: 0 }),
    enabled: !!accessToken,
    // WHY 5min staleTime: news changes constantly but workspace shouldn't hammer S9.
    // 5 minutes is fresh enough to show recent catalysts without excessive polling.
    staleTime: 5 * 60_000,
  });

  if (isLoading) {
    return (
      <div className="space-y-px">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-0.5 px-2 h-[22px] justify-center">
            <Skeleton className="h-2.5 w-full" style={{ animationDelay: `${i * 40}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        News unavailable.
      </p>
    );
  }

  const articles = data.articles ?? [];

  if (articles.length === 0) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        No news articles yet.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border/30">
      {articles.map((article) => (
        <a
          key={article.article_id}
          href={safeExternalUrl(article.url)}
          target="_blank"
          rel="noopener noreferrer"
          // WHY h-[22px]: §0.2 mandates 22px row height for all data rows.
          // group: enables group-hover styling for child elements.
          className="group flex items-center gap-2 px-2 h-[22px] hover:bg-muted/40"
        >
          {/* Article title — single line, truncated */}
          <span className="flex-1 truncate text-[11px] text-foreground group-hover:text-primary">
            {article.title}
          </span>

          {/* Timestamp — right-aligned monospace per §0.1 */}
          <time
            dateTime={article.published_at ?? undefined}
            className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground"
          >
            {formatRelativeTime(article.published_at)}
          </time>

          {/* High-relevance badge — only for top-signal articles */}
          {article.display_relevance_score != null && article.display_relevance_score >= 0.7 && (
            <span className="shrink-0 rounded-[2px] bg-positive/10 px-1 text-[9px] font-semibold tabular-nums text-positive">
              {Math.round(article.display_relevance_score * 100)}
            </span>
          )}
        </a>
      ))}

      {/* Footer — compact link to full news/alerts page */}
      <div className="flex h-[22px] items-center px-2 border-t border-border/30">
        <Link
          href="/alerts"
          className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
        >
          View all news →
        </Link>
      </div>
    </div>
  );
}
