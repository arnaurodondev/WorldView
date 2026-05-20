/**
 * components/primitives/MetricValue.tsx — formatted numeric metric value
 * (PRD-0089 F1: promoted from instrument/shared/ to cross-page primitives)
 *
 * WHY THIS EXISTS: every numeric value on the instrument page must share one
 * typography token (PRD-0088 §6.11: 11px IBM Plex Mono + tabular-nums) and one
 * "missing data" convention. Centralising here prevents juniors rendering
 * "null" as text or using a proportional font (which jitters columns).
 * WHO USES IT: metric rows/cells across Quote, Financials, Intelligence tabs.
 * DATA SOURCE: Pure presentational primitive (no data / state / effects).
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.11 + colour palette.
 * TARGET READER: junior Next.js dev. tabular-nums = equal-width digits so
 *   "12.34" and "78.56" align vertically. "—" is the finance placeholder for
 *   *absent* data — NOT a loading state (use <Skeleton/> for loading).
 */

import type { ReactNode } from "react";

type MetricColor = "positive" | "negative" | "amber" | "muted" | "default";

interface MetricValueProps {
  /** Formatted display string. null / undefined → "—" fallback. */
  readonly children: ReactNode;
  /** Semantic colour intent (defaults to body text). */
  readonly color?: MetricColor;
}

// WHY this map (not inline ternaries): one place to audit colour usage.
// positive=up/gain, negative=down/loss, amber=caution, muted=de-emphasised,
// default=neutral body text.
const COLOR_CLASS: Record<MetricColor, string> = {
  positive: "text-positive",
  negative: "text-negative",
  // WHY text-warning (not text-amber-400): the architecture test
  // __tests__/architecture/no-off-palette-colors.test.ts bans raw Tailwind
  // amber-N classes; `--warning` resolves to #FFB000 (Bloomberg amber).
  amber: "text-warning",
  muted: "text-muted-foreground",
  default: "text-foreground",
};

export function MetricValue({ children, color = "default" }: MetricValueProps) {
  // WHY "—" for null/undefined: finance UX convention for *absent* data
  // (intentionally missing, not loading). Faded /50 opacity prevents the dash
  // from competing visually with real data on the same row.
  if (children === null || children === undefined) {
    return <span className="text-[11px] font-mono tabular-nums text-muted-foreground/50">—</span>;
  }
  return <span className={`text-[11px] font-mono tabular-nums ${COLOR_CLASS[color]}`}>{children}</span>;
}
