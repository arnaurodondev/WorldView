/**
 * components/instrument/InstrumentTopNews.tsx — Top 4 articles by market impact
 *
 * WHY THIS EXISTS: The Overview tab's 3-column lower grid needs a news panel
 * (center column) showing the 4 most market-relevant articles. Analysts opening
 * an instrument page want to immediately see "what's driving this?" before
 * switching to the full News tab.
 *
 * WHY TOP 4 (not 5 or 10): 4 rows × 22px = 88px — fits in the lower grid
 * without overflowing, and 4 articles is enough context for an initial scan.
 *
 * WHY order_by=market_impact_score: We want the most price-relevant articles,
 * not just the most recent. Market impact is S6's composite scoring signal
 * (PRD-0026) that weights price movement correlation with publication time.
 *
 * WHY routing_tier badge: HI/STD/LO signals help analysts instantly identify
 * which articles are analyst-grade (HI) vs routine (STD/LO).
 *
 * WHO USES IT: OverviewLayout (within the 3-column lower grid, center column)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/articles?limit=4&order_by=market_impact_score
 * DESIGN REFERENCE: PRD-0031 §9 OverviewLayout zone 3, Wave 5
 */

"use client";
// WHY "use client": uses useQuery for data fetching.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatRelativeTime } from "@/lib/utils";
import type { RankedArticle } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface InstrumentTopNewsProps {
  entityId: string;
  /** Callback to switch parent page to the News tab */
  onViewAll: () => void;
}

// ── Tier badge helpers ────────────────────────────────────────────────────────
// WHY separate style map (not inline ternary): keeps the badge color logic
// in one place; adding a new tier only requires one change here.
// Note: RankedArticle.routing_tier uses "LIGHT" | "MEDIUM" | "DEEP" (not "STANDARD"/"HIGH")
// WHY handle both naming conventions: the Article type uses "HIGH"/"STANDARD"/"LIGHT"
// while RankedArticle uses "LIGHT"/"MEDIUM"/"DEEP". The map handles both.
const TIER_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  DEEP:     { bg: "bg-positive/20", text: "text-positive",            label: "HI"  },
  HIGH:     { bg: "bg-positive/20", text: "text-positive",            label: "HI"  },
  MEDIUM:   { bg: "bg-muted",       text: "text-muted-foreground",    label: "MED" },
  STANDARD: { bg: "bg-muted",       text: "text-muted-foreground",    label: "STD" },
  LIGHT:    { bg: "bg-muted/60",    text: "text-muted-foreground/60", label: "LO"  },
};

// ── Article row sub-component ─────────────────────────────────────────────────

/**
 * ArticleRow — single 22px article row with tier badge + title + time
 *
 * WHY 22px row (not ArticleCard): ArticleCard has internal padding and full source/
 * summary display which is too large for the compact Overview grid panel. This
 * inline row is "scannable" — analysts read the title and tier in <1 second.
 *
 * WHY RankedArticle (not Article): getEntityNews returns RankedArticle[] since
 * Wave 7 retargeted the entity news proxy to S6 (which returns the ranked shape).
 */
function ArticleRow({ article }: { article: RankedArticle }) {
  const tier = article.routing_tier;
  const tierStyle = tier ? TIER_STYLES[tier] : null;

  return (
    <div
      className="flex items-center h-[22px] px-2 gap-1.5 border-b border-border/30 hover:bg-muted/40 cursor-pointer last:border-0"
      onClick={() => {
        // WHY window.open: articles are external URLs; client-side navigation
        // only works for internal Next.js routes. Open in new tab.
        if (article.url) window.open(article.url, "_blank", "noopener,noreferrer");
      }}
    >
      {/* Routing tier badge — HI/MED/LO visual signal */}
      {tierStyle && (
        <span
          className={`rounded-[2px] px-1 text-[9px] font-mono shrink-0 ${tierStyle.bg} ${tierStyle.text}`}
        >
          {tierStyle.label}
        </span>
      )}

      {/* Article title — truncated to fit the column */}
      <span className="text-[11px] text-foreground truncate flex-1">
        {article.title ?? "Untitled"}
      </span>

      {/* Relative time — compact right-aligned */}
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
        {formatRelativeTime(article.published_at)}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InstrumentTopNews({ entityId, onViewAll }: InstrumentTopNewsProps) {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["entity-news-top4", entityId],
    queryFn: () =>
      createGateway(accessToken).getEntityNews(entityId, {
        limit: 4,
        offset: 0,
        // WHY display_relevance_score (not market_impact_score): EntityNewsParams
        // only accepts 'display_relevance_score' | 'published_at'. display_relevance_score
        // is the composite score (0.5*market + 0.4*llm + 0.1*routing) which is the
        // best available proxy for market impact at the API level.
        order_by: "display_relevance_score",
      }),
    staleTime: 60_000,
    enabled: !!accessToken && !!entityId,
  });

  return (
    <div>
      {/* Section header */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOP NEWS
        </span>
      </div>

      {/* Loading state — 4 skeleton rows matching actual row height */}
      {isLoading && (
        <>
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center h-[22px] px-2 gap-1.5 border-b border-border/30 last:border-0">
              <Skeleton className="h-3 w-6 shrink-0" />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-12 shrink-0" />
            </div>
          ))}
        </>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <InlineEmptyState message="News unavailable." className="px-2 py-1.5 text-[11px]" />
      )}

      {/* Empty state — no articles for this entity */}
      {!isLoading && !isError && (!data?.articles || data.articles.length === 0) && (
        <InlineEmptyState message="No recent news." className="px-2 py-1.5 text-[11px]" />
      )}

      {/* Article rows */}
      {!isLoading && !isError && data?.articles && data.articles.length > 0 && (
        <>
          {data.articles.map((article) => (
            <ArticleRow key={article.article_id} article={article} />
          ))}
        </>
      )}

      {/* Footer: "More news" link switches parent to the News tab */}
      {/* WHY always show footer: the callback link is always useful even when
          there are no articles in the top-4 (e.g., to check full news list). */}
      <div className="flex items-center px-2 h-[22px]">
        <button
          onClick={onViewAll}
          className="text-[10px] text-primary"
        >
          → More news
        </button>
      </div>
    </div>
  );
}
