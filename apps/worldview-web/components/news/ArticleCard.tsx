/**
 * components/news/ArticleCard.tsx — News article card for feeds and timelines
 *
 * WHY THIS EXISTS: News articles appear in at least 5 places:
 *   1. Dashboard WatchlistNews widget (F-5)
 *   2. Alerts/News page → News Feed tab (F-7)
 *   3. Alerts/News page → Top Today tab (F-7)
 *   4. Instrument Detail → News tab (F-6)
 *   5. Workspace → NewsPanel (F-12)
 *
 * A shared ArticleCard ensures consistent layout, scoring, and interaction
 * across all call sites. The alternative — inline card HTML in each page —
 * would create five diverging implementations.
 *
 * WHO USES IT: NewsTimeline (in this wave), WatchlistNews upgrade (F-5 post-merge),
 * InstrumentNewsTab (F-6), NewsPanel (F-12).
 *
 * DATA SOURCE: Article type from types/api.ts (PRD-0026 §6.2 News Routes)
 * DESIGN REFERENCE: PRD-0028 §6.5 news/ArticleCard.tsx
 */

// WHY no "use client": ArticleCard is a pure presentational component.
// No hooks, no browser APIs, no event handlers that require client context.
// It can run as a Server Component OR be imported into a client component.
// The parent page/feed component holds the data-fetching and "use client" boundary.

import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ArticleImpactBadge } from "@/components/news/ArticleImpactBadge";
import { cn, formatRelativeTime, safeExternalUrl } from "@/lib/utils";
import type { Article, RankedArticle } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ArticleCardProps {
  /**
   * Article object from S9 GET /v1/news/* endpoints.
   * WHY union type: two endpoints return different shapes:
   *   - getRelevantNews → Article (legacy S5 format with source, summary, tickers, sentiment)
   *   - getTopNews / getEntityNews → RankedArticle (S6 format with source_name, impact_windows)
   * ArticleCard handles both gracefully using type narrowing helpers below.
   */
  article: Article | RankedArticle;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * ArticleCard — card showing a single news article with scoring metadata.
 *
 * Layout (top → bottom):
 *   [source badge] .................. [published_at relative time]
 *   [title — clickable link to article URL, opens new tab]
 *   [summary — 2-line clamp, only if available]
 *   [entity tickers] ............. [ArticleImpactBadge score+sentiment]
 */
// ── Type narrowing helpers ────────────────────────────────────────────────────
//
// WHY helpers instead of inline casts: keeps the JSX clean and centralises the
// "which field does this shape use?" logic. If the API ever unifies the shapes,
// only these helpers need updating.

/** Return the human-readable source label from whichever article shape we have. */
function getSource(a: Article | RankedArticle): string {
  // Article has `source: string`; RankedArticle has `source_name: string | null`.
  return ('source' in a ? a.source : a.source_name) ?? '—';
}

/** Return the optional summary text (only Article has this field). */
function getSummary(a: Article | RankedArticle): string | null {
  return 'summary' in a ? a.summary : null;
}

/** Return tickers to display (only Article has this field; RankedArticle does not). */
function getTickers(a: Article | RankedArticle): string[] {
  return 'tickers' in a ? a.tickers : [];
}

/** Return sentiment label (only Article has this field; RankedArticle does not). */
function getSentiment(a: Article | RankedArticle): "positive" | "negative" | "neutral" | null {
  // WHY explicit return type: ArticleImpactBadge expects the exact union from Article.
  // If `a` is RankedArticle (no sentiment field), we return null → badge renders nothing.
  return 'sentiment' in a ? a.sentiment : null;
}

export function ArticleCard({ article }: ArticleCardProps) {
  // WHY isLightTier: LIGHT routing tier = low-relevance/low-signal article. De-emphasised
  // at 60% opacity so traders can focus on HIGH/STANDARD signal articles. The italic source
  // badge reinforces "lower confidence" routing without hiding the article entirely.
  // WHY ?? false: RankedArticle.routing_tier is string | null; null → not LIGHT.
  const isLightTier = (article.routing_tier ?? '') === "LIGHT";

  const source = getSource(article);
  const summary = getSummary(article);
  const tickers = getTickers(article);
  const sentiment = getSentiment(article);

  return (
    // WHY group class: enables group-hover on child elements (title colour, icon opacity)
    // WHY hover:bg-muted/30 (not hover:bg-card/80): bg-card/80 is barely visible
    // against bg-card (#111820). bg-muted/30 (#1A2030 at 30%) creates a noticeable
    // lift effect that signals interactivity without being distracting.
    <article className={cn(
      "group rounded-lg border border-border/50 bg-card p-3 transition-colors hover:border-border hover:bg-muted/30",
      isLightTier && "opacity-60",  // WHY: de-emphasise LIGHT-tier; opacity on the wrapper dims the entire card
    )}>

      {/* ── Top row: source + timestamp ────────────────────────────────────── */}
      <div className="mb-1.5 flex items-center justify-between gap-2">
        {/* Source badge — secondary variant for neutral, muted appearance */}
        <Badge variant="secondary" className={cn(
          "shrink-0 text-[10px] uppercase tracking-wider",
          isLightTier && "italic",  // WHY: italic signals "lower confidence" source routing to traders
        )}>
          {source}
        </Badge>

        {/* Relative published time — font-mono tabular-nums per global rule */}
        {/* WHY relative not absolute: "2h ago" conveys recency instantly; absolute
            ISO time would require mental arithmetic while scanning a feed. */}
        <time
          dateTime={article.published_at ?? undefined}
          className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground"
        >
          {formatRelativeTime(article.published_at)}
        </time>
      </div>

      {/* ── Title — external link ───────────────────────────────────────────── */}
      {/* WHY target="_blank" rel="noopener noreferrer": articles are third-party
          URLs. Opening in a new tab keeps the user in the app. noopener prevents
          the new page from accessing window.opener (security). noreferrer stops
          the referrer header leaking the app URL to third-party publishers. */}
      <a
        href={safeExternalUrl(article.url)}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-1.5 block text-sm font-medium leading-snug text-foreground transition-colors group-hover:text-primary"
      >
        <span className="flex items-start gap-1">
          <span className="line-clamp-2 flex-1">{article.title}</span>
          {/* External link icon — only appears on hover to reduce visual noise */}
          <ExternalLink
            className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
            aria-hidden="true"
          />
        </span>
      </a>

      {/* ── Summary — only if available, 2-line clamp ──────────────────────── */}
      {/* WHY conditional: ~40% of articles have no summary. RankedArticle has no
          summary field at all; getSummary() returns null for those. The empty string
          check handles both null and "" from the API without layout shift. */}
      {summary && summary.trim() !== "" && (
        <p className="mb-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {summary}
        </p>
      )}

      {/* ── Bottom row: entity tickers + impact badge ───────────────────────── */}
      <div className="flex items-center justify-between gap-2">
        {/* Entity tickers — as outline badges */}
        {/* WHY show tickers (not entity_ids): entity IDs are UUIDs; tickers like
            "AAPL" are immediately meaningful to traders. RankedArticle has no
            tickers field (getTickers() returns []); the div renders empty. */}
        <div className="flex flex-wrap gap-1">
          {tickers.slice(0, 4).map((ticker) => (
            // Link to instrument detail page so user can pivot on mention
            <Link
              key={ticker}
              href={`/instruments?q=${encodeURIComponent(ticker)}`}
              onClick={(e) => e.stopPropagation()} // WHY: prevent bubbling to card click
              className="rounded border border-border/70 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-foreground hover:border-primary/50 hover:text-primary"
            >
              {ticker}
            </Link>
          ))}
          {/* Show overflow count if more than 4 tickers */}
          {tickers.length > 4 && (
            <span className="px-1 text-[10px] text-muted-foreground">
              +{tickers.length - 4}
            </span>
          )}
        </div>

        {/* Article impact score badge — renders nothing if score is null */}
        <ArticleImpactBadge
          score={article.display_relevance_score}
          sentiment={sentiment}
        />
      </div>
    </article>
  );
}
