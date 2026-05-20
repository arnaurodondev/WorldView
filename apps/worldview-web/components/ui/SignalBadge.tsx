/**
 * components/ui/SignalBadge.tsx — Market sentiment signal indicator.
 *
 * WHY THIS EXISTS (DS-008, CRIT-002, FR-10.6):
 * Sentiment was previously rendered as icon-only (TrendingUp/Down/Zap).
 * Color-blind users see nothing; non-traders don't recognize the icons
 * without labels. This component adds the explicit BULLISH/BEARISH/NEUTRAL
 * text label alongside the icon, satisfying:
 *   - ADR-F-15 (semantic color via tokens, not inline hex)
 *   - WCAG 1.4.1 (use of color — non-color cue must convey same info)
 *   - §6.11b colour-blind safe encoding (icon + label = redundant coding)
 *
 * USAGE:
 *   <SignalBadge sentiment="bullish" />       → green TrendingUp + "BULLISH"
 *   <SignalBadge sentiment="bearish" />       → red TrendingDown + "BEARISH"
 *   <SignalBadge sentiment="neutral" />       → muted Minus + "NEUTRAL"
 *   <SignalBadge sentiment={null} />          → renders nothing
 *
 * WHY null renders null (not a placeholder):
 * When sentiment is unknown (e.g. S6 hasn't scored the article yet) we hide
 * the badge entirely rather than show "NEUTRAL" — showing a neutral badge
 * implies the system scored it, which would be misleading.
 *
 * USED BY: ArticleCard, news page article rows, S6 signals panel.
 * Replaces: ad-hoc icon renders in news/page.tsx:256-263 and ArticleCard.tsx:102-110.
 */

import type { ComponentType } from "react";

import { Minus, TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export type Sentiment = "bullish" | "bearish" | "neutral";

export interface SignalBadgeProps {
  /** The sentiment direction to render. null/undefined → nothing rendered. */
  sentiment: Sentiment | null | undefined;
  /** Optional extra class names on the outer flex container. */
  className?: string;
}

// ── Config per sentiment ──────────────────────────────────────────────────────

// WHY inline config (not switch): keeps icon, label, and color co-located —
// easier to audit that all three are consistent when changing a sentiment tier.
const SENTIMENT_CONFIG = {
  bullish: {
    // TrendingUp: universally recognised as "price going up" in finance UIs.
    Icon: TrendingUp,
    label: "BULLISH",
    // text-positive: institutional green token (ADR-F-15, --positive = #00D26A).
    // Never use text-green-* — those bypass the token system and won't update
    // when the palette changes.
    colorClass: "text-positive",
  },
  bearish: {
    // TrendingDown: inverse of TrendingUp — directional icon pair is standard.
    Icon: TrendingDown,
    label: "BEARISH",
    // text-negative: institutional red token (--negative = #FF3B5C).
    colorClass: "text-negative",
  },
  neutral: {
    // Minus: flat / no-directional signal — zero-slope interpretation.
    Icon: Minus,
    label: "NEUTRAL",
    // text-muted-foreground: de-emphasised; neutral is the absence of a signal
    // rather than a positive assertion, so it should recede visually.
    colorClass: "text-muted-foreground",
  },
} as const satisfies Record<
  Sentiment,
  { Icon: ComponentType<{ className?: string }>; label: string; colorClass: string }
>;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SignalBadge — sentiment direction indicator with icon + text label.
 *
 * Renders null for null/undefined sentiment so callers need no conditional
 * wrapper. Size is intentionally tiny (text-[10px]) so the badge fits inline
 * within compact 22px article rows without disrupting line height.
 */
export function SignalBadge({ sentiment, className }: SignalBadgeProps) {
  // WHY return null (not empty fragment): React skips the DOM node entirely,
  // preserving column alignment without an invisible placeholder element.
  if (!sentiment) return null;

  const config = SENTIMENT_CONFIG[sentiment];
  if (!config) return null;

  const { Icon, label, colorClass } = config;

  return (
    <span
      className={cn(
        // flex + gap: icon and text sit side-by-side on a single baseline.
        "flex items-center gap-0.5",
        // text-[10px] / uppercase / tracking-wide: all-caps badge style.
        // 10px is the minimum approved size (DESIGN_SYSTEM §3.2 exception table).
        "text-[10px] uppercase tracking-wide font-medium",
        colorClass,
        className,
      )}
      // WHY aria-label: the icon alone isn't announced by screen readers as
      // directional content. The composite label gives SR users the same info
      // as sighted users without requiring them to interpret icon semantics.
      aria-label={label}
    >
      {/* Icon at 10px (size-2.5 = 10px) to match the text cap height */}
      <Icon className="size-2.5 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
