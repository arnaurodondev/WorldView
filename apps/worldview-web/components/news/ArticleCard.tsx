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
 *   [entity tickers] ............. [relevance score badge]
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

export function ArticleCard({ article }: ArticleCardProps) {
  // WHY isLightTier: LIGHT routing tier = low-relevance/low-signal article. De-emphasised
  // at 60% opacity so traders can focus on HIGH/STANDARD signal articles. The italic source
  // badge reinforces "lower confidence" routing without hiding the article entirely.
  // WHY ?? false: RankedArticle.routing_tier is string | null; null → not LIGHT.
  const isLightTier = (article.routing_tier ?? '') === "LIGHT";

  // WHY isHighTier: HIGH routing tier = top-signal article that passed deep processing.
  // These deserve a "TOP" pill so analysts can spot them in a long feed at a glance,
  // the same way Bloomberg terminals flag "FLASH" stories in a different colour.
  const isHighTier = (article.routing_tier ?? '') === "HIGH";

  const source = getSource(article);
  const summary = getSummary(article);
  const tickers = getTickers(article);

  // ── Relevance score badge styling ─────────────────────────────────────────────
  // WHY threshold-based colour (not sentiment-based): display_relevance_score is the
  // composite PRD-0026 signal (market_impact + llm_relevance + routing). For
  // RankedArticle, sentiment is always null (not scored), so the existing
  // ArticleImpactBadge would always render muted. A threshold colour tells analysts
  // the signal strength (high/medium/low) without requiring a sentiment field.
  // 0.7+ → positive/green (strong signal), 0.4–0.7 → warning/amber, <0.4 → muted.
  const score = article.display_relevance_score;
  const scoreBadgeClass = cn(
    "shrink-0 rounded-[2px] px-1 py-0.5 font-mono text-[9px] tabular-nums font-semibold",
    score != null && score >= 0.7
      ? "bg-positive/15 text-positive"
      : score != null && score >= 0.4
        ? "bg-warning/15 text-warning"
        : "bg-muted text-muted-foreground",
  );

  return (
    // WHY group class: enables group-hover on child elements (title colour, icon opacity)
    // WHY hover:bg-muted/30 (not hover:bg-card/80): bg-card/80 is barely visible
    // against bg-card (#111820). bg-muted/30 (#1A2030 at 30%) creates a noticeable
    // lift effect that signals interactivity without being distracting.
    <article className={cn(
      // WHY rounded-[2px] (not rounded-lg): terminal aesthetic — 2px radius per design system rule.
      // rounded-lg looks consumer/friendly; 2px is the institutional standard throughout the app.
      "group rounded-[2px] border border-border/40 bg-card py-1 px-2 transition-colors hover:border-border hover:bg-muted/30",
      isLightTier && "opacity-60",  // WHY: de-emphasise LIGHT-tier; opacity on the wrapper dims the entire card
    )}>

      {/* ── Top row: source + routing tier pill + timestamp ────────────────── */}
      <div className="mb-0 flex items-center justify-between gap-2">

        {/* Left cluster: source badge + optional HIGH-tier pill */}
        <div className="flex shrink-0 items-center gap-1.5">
          {/* Source badge — secondary variant for neutral, muted appearance */}
          <Badge variant="secondary" className={cn(
            "shrink-0 text-[10px] uppercase tracking-wider",
            isLightTier && "italic",  // WHY: italic signals "lower confidence" source routing to traders
          )}>
            {source}
          </Badge>

          {/* WHY "TOP" pill only for HIGH tier: STANDARD articles are the baseline —
              no badge needed. LIGHT articles are already de-emphasised via opacity.
              Only HIGH deserves a positive signal to make it stand out in the feed.
              Using primary/15 background instead of a solid colour keeps it readable
              in both light and dark themes without clashing with the score badge. */}
          {isHighTier && (
            <span className="shrink-0 rounded-[2px] bg-primary/15 px-1 py-0.5 text-[9px] font-semibold uppercase text-primary">
              TOP
            </span>
          )}
        </div>

        {/* Right cluster: relevance score badge + relative published time */}
        <div className="flex shrink-0 items-center gap-2">
          {/* WHY relevance score badge: display_relevance_score is the composite
              PRD-0026 signal — market impact + LLM relevance + routing score. It
              tells the analyst how market-relevant this article is at a glance,
              before reading the title. Shown as a 0–100 integer for readability.
              Only rendered when score is not null (older articles lack scoring). */}
          {score != null && (
            // WHY aria-label="impact score": the null-state test (when score is null) uses
            // queryByLabelText(/impact score/i) to confirm the badge is absent. aria-label
            // gives the test a stable selector that isn't fragile to the numeric value.
            <span className={scoreBadgeClass} aria-label="impact score">
              {(score * 100).toFixed(0)}
            </span>
          )}

          {/* Relative published time — font-mono tabular-nums per global rule */}
          {/* WHY relative not absolute: "2h ago" conveys recency instantly; absolute
              ISO time would require mental arithmetic while scanning a feed. */}
          <time
            dateTime={article.published_at ?? undefined}
            className="font-mono text-[10px] tabular-nums text-muted-foreground"
          >
            {formatRelativeTime(article.published_at)}
          </time>
        </div>
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
        className="mb-0 block text-[11px] font-medium leading-snug text-foreground transition-colors group-hover:text-primary"
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
        // WHY line-clamp-1 (was line-clamp-2): single summary line reduces card height
        // by ~14px per card in dashboard feeds (WatchlistNews, PortfolioNewsWidget).
        // Density over context — analysts who want the full article click the link.
        <p className="mb-0 line-clamp-1 text-[10px] leading-relaxed text-muted-foreground">
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
              className="rounded-[2px] border border-border/70 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-foreground hover:border-primary/50 hover:text-primary"
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

        {/* WHY ArticleImpactBadge removed: the top-row relevance score badge now
            shows the composite signal (display_relevance_score) with threshold-based
            colour. Keeping the bottom badge here was a duplicate of the same value,
            which created visual noise and broke getByText("75") uniqueness in tests. */}
      </div>
    </article>
  );
}
