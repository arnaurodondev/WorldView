/**
 * components/ui/sentiment-badge.tsx — Compact pill badge for article-level sentiment.
 *
 * WHY THIS EXISTS (PLAN-0091 C-2): The news rail in the Intelligence tab shows
 * 30+ articles above the fold. Analysts need to instantly identify article
 * sentiment without reading the headline — a compact pill badge (POS/NEG/NEU/MIX)
 * lets the eye sweep the column and spot clusters of positive or negative news
 * for a given entity in <1 second, the way Bloomberg's sentiment column works.
 *
 * WHY "mixed" is distinct from "neutral":
 * "neutral" = the LLM scored the article as not taking a directional stance.
 * "mixed" = the article covers both positive AND negative events (e.g. "Company
 * beats earnings but guides down"). Conflating them would hide useful signal.
 *
 * WHY return null for null/undefined (not render a placeholder):
 * LIGHT-tier articles skip the LLM scoring step. Showing "NEU" for them would
 * falsely imply the article was scored and found neutral. Hiding the badge is
 * the honest representation.
 *
 * WHO USES IT: DenseArticleRow (via NewsColumn) in the Intelligence tab.
 * DATA SOURCE: RankedArticle.sentiment from GET /v1/news/entity/{id} (S6/S9).
 * DESIGN REFERENCE: PLAN-0091 C-2 spec §Item 1.
 */

import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Article-level sentiment variants matching the RankedArticle.sentiment field. */
export type ArticleSentiment = "positive" | "negative" | "neutral" | "mixed";

export interface SentimentBadgeProps {
  /** The categorical sentiment from ArticleRelevanceScoringWorker. null → render nothing. */
  sentiment: ArticleSentiment | null | undefined;
  /** Optional extra classes on the pill span. */
  className?: string;
}

// ── Config per sentiment ──────────────────────────────────────────────────────

// WHY a config map (not a switch): keeps label and color classes co-located so
// adding a new variant requires editing exactly one place. The `satisfies`
// constraint catches any missing variant at compile time.
const BADGE_CONFIG = {
  positive: {
    label: "POS",
    // bg-[#26A69A]/10: teal tint at 10% opacity for dark-theme subtlety.
    // text-[#26A69A]: standard finance positive color (same as text-positive token).
    // border-[#26A69A]/30: 30% opacity border so the outline reads without overpowering.
    className: "bg-[#26A69A]/10 text-[#26A69A] border-[#26A69A]/30",
  },
  negative: {
    label: "NEG",
    // bg-[#EF5350]/10: red tint at 10% opacity (finance negative, same as text-negative).
    className: "bg-[#EF5350]/10 text-[#EF5350] border-[#EF5350]/30",
  },
  neutral: {
    label: "NEU",
    // bg-muted/20: near-invisible fill; neutral should recede vs directional signals.
    className: "bg-muted/20 text-muted-foreground border-muted/30",
  },
  mixed: {
    label: "MIX",
    // bg-[#FFB000]/10: amber/warning tint — "mixed" is an ambiguous signal that
    // warrants analyst attention but isn't a clear directional bet.
    className: "bg-[#FFB000]/10 text-[#FFB000] border-[#FFB000]/30",
  },
} as const satisfies Record<ArticleSentiment, { label: string; className: string }>;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SentimentBadge — compact pill badge for article-level sentiment.
 *
 * Renders nothing for null/undefined so callers need no conditional wrapper.
 * Designed to sit inline in 18px dense news rows without disrupting line height.
 */
export function SentimentBadge({ sentiment, className }: SentimentBadgeProps) {
  // WHY return null (not an empty fragment): React skips the DOM node entirely,
  // preserving column alignment without an invisible placeholder box.
  if (!sentiment) return null;

  const config = BADGE_CONFIG[sentiment];
  // Guard against future backend sentiment values not yet reflected in the type.
  if (!config) return null;

  return (
    <span
      className={cn(
        // Pill shape: rounded-full gives the capsule outline expected of badges.
        // text-[9px]: sub-label size — small enough to fit in 18px rows while
        // remaining legible (9px is the minimum approved size per DESIGN_SYSTEM §3.2).
        // px-1.5 py-0: horizontal padding only — vertical padding would push row height.
        // border: one-pixel outline in the sentiment colour at 30% opacity.
        "text-[9px] font-mono px-1.5 py-0 rounded-full border",
        config.className,
        className,
      )}
      // WHY aria-label: screen readers announce "POS" as a string, which is cryptic.
      // The full label gives SR users the same meaning as sighted users.
      aria-label={`sentiment: ${sentiment}`}
    >
      {config.label}
    </span>
  );
}
