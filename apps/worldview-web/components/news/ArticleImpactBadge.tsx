/**
 * components/news/ArticleImpactBadge.tsx — Article market impact score badge
 *
 * WHY THIS EXISTS: News articles from PRD-0026 carry a `display_relevance_score`
 * (0.0–1.0 float) and a `sentiment` field. This badge converts the float to a
 * 0–100 integer and colours it by sentiment so traders can instantly judge
 * article impact weight without reading the full score.
 *
 * WHY A SEPARATE COMPONENT: The same badge appears in ArticleCard, the dashboard
 * WatchlistNews widget, and the Instrument Detail news tab. Extracting it
 * guarantees visual consistency across all three call sites.
 *
 * WHO USES IT: ArticleCard (F-7), future InstrumentNewsTab (F-6).
 * DATA SOURCE: Article.display_relevance_score + Article.sentiment (PRD-0026)
 * DESIGN REFERENCE: PRD-0028 §6.5 news components — impact score badge
 */

// WHY no "use client": this component has no hooks, no event handlers,
// and no browser APIs. It is a pure Server Component (or renders fine on
// the client when imported into a client component).

import type { Article } from "@/types/api";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ArticleImpactBadgeProps {
  /** 0.0–1.0 relevance score from PRD-0026 API; null = score not available */
  score: number | null;
  /** Sentiment label from PRD-0026 NLP pipeline; null = not scored */
  sentiment: Article["sentiment"];
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * ArticleImpactBadge — renders a compact "NN" score badge coloured by sentiment.
 *
 * WHY no rendering when score is null: Showing "—" would clutter every card
 * for older articles that predate the PRD-0026 scoring pipeline. Returning
 * null collapses the badge slot entirely.
 */
export function ArticleImpactBadge({ score, sentiment }: ArticleImpactBadgeProps) {
  // Do not render anything if the score has not been computed yet.
  // WHY: Older articles don't have scoring data; hiding the badge is cleaner
  // than showing a placeholder that would confuse traders into thinking it
  // means something.
  if (score === null || score === undefined) {
    return null;
  }

  // Convert 0.0–1.0 float to 0–100 integer.
  // WHY Math.round (not Math.floor): 0.756 → 76 is more accurate than 75.
  const displayScore = Math.round(score * 100);

  // ── Colour mapping by sentiment ─────────────────────────────────────────────
  // WHY inline hex (not Tailwind color): Midnight Pro palette tokens must stay
  // consistent; using arbitrary [#hex] in className ensures no dependency on
  // Tailwind colour name changes in future upgrades.
  const scoreColorClass = cn(
    "font-mono text-xs font-semibold tabular-nums",
    sentiment === "positive" && "text-[#26A69A]",   // Midnight Pro positive (teal)
    sentiment === "negative" && "text-[#EF5350]",   // Midnight Pro negative (red)
    // neutral or null sentiment → muted foreground (no emphasis)
    (sentiment === "neutral" || sentiment === null) && "text-muted-foreground",
  );

  // ── Sentiment label ──────────────────────────────────────────────────────────
  // WHY abbreviated: space in ArticleCard bottom row is tight; "+" / "−" / "~"
  // conveys the signal faster than the full word.
  const sentimentSymbol =
    sentiment === "positive" ? "+" :
    sentiment === "negative" ? "−" :
    "~";

  return (
    // WHY flex gap: keeps score and symbol tightly coupled, both font-mono
    <span className="inline-flex items-center gap-0.5" aria-label={`Impact score: ${displayScore}`}>
      {/* Score as integer — font-mono tabular-nums per global rule */}
      <span className={scoreColorClass}>{displayScore}</span>
      {/* Sentiment symbol for quick visual scanning */}
      <span className={cn("text-[10px]", scoreColorClass)}>{sentimentSymbol}</span>
    </span>
  );
}
