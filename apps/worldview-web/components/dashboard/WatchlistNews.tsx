/**
 * components/dashboard/WatchlistNews.tsx — Latest news feed widget
 *
 * WHY THIS EXISTS: Information edge requires reading news as it breaks.
 * A news feed on the dashboard means traders don't need to leave their
 * current view to stay informed. The 48h window captures today + yesterday.
 *
 * WHY SIMPLE LINK CARDS (not ArticleCard from F-7):
 * F-7 hasn't been built yet. This widget uses a minimal inline card pattern
 * that will be upgraded to ArticleCard once F-7 is complete.
 * The data shape is identical — only the visual treatment changes.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/news/top?hours=48&limit=10
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard WatchlistNews
 */

"use client";
// WHY "use client": uses useQuery.

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { safeExternalUrl } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistNews() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["news-top-dashboard"],
    queryFn: () => createGateway(accessToken).getTopNews({ hours: 48, limit: 10 }),
    enabled: !!accessToken,
    // WHY 5min: news doesn't change every second; 5min freshness is reasonable
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-4 w-full" style={{ animationDelay: `${i * 50}ms` }} />
            <Skeleton className="h-3 w-3/4" style={{ animationDelay: `${i * 50}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY muted (not destructive red): news service being offline is a backend
  // issue, not a user error. Muted text is professional; red looks broken.
  if (isError) {
    return (
      <p className="text-sm text-muted-foreground">
        News feed unavailable — articles will appear once the content pipeline runs.
      </p>
    );
  }

  const articles = data?.articles ?? [];

  // ── Empty state ────────────────────────────────────────────────────────────
  if (articles.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No recent news</p>
    );
  }

  return (
    <div className="space-y-2">
      {articles.map((article) => (
        <a
          key={article.article_id}
          href={safeExternalUrl(article.url)}
          target="_blank"
          rel="noopener noreferrer"
          className="group block rounded border border-border/50 p-2 hover:border-border hover:bg-muted/30"
        >
          {/* Article headline */}
          <p className="line-clamp-2 text-xs font-medium leading-snug text-foreground group-hover:text-primary">
            {article.title}
          </p>
          {/* Source + timestamp */}
          {/* WHY source_name: getTopNews now returns RankedArticle (S6) which uses
              source_name (e.g. "EODHD") instead of source (legacy Article field). */}
          <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
            <span>{article.source_name ?? '—'}</span>
            <span className="font-mono tabular-nums">
              {article.published_at ? relativeTime(article.published_at) : '—'}
            </span>
            <ExternalLink className="ml-auto h-2.5 w-2.5 opacity-0 group-hover:opacity-100" />
          </div>
        </a>
      ))}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * relativeTime — human-readable relative timestamp
 * WHY: "2h ago" is faster to scan than "2026-04-18T14:32:00Z" for a news feed
 */
function relativeTime(isoStr: string): string {
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}
