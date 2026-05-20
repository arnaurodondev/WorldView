/**
 * components/instrument/quote/metrics/MetricGroupDivider.tsx — group separator
 *
 * WHY: PRD-0088 §6.7.2 groups 26 stat rows into 5 clusters (Valuation,
 * Margins, Leverage, Yield, 52W Range). A subtle hairline between groups
 * gives the eye a rest point without adding the vertical bulk of a header.
 * WHY h-[1px] + /30 opacity: whispers rather than shouts so data stays primary.
 * WHY mx-3: aligns with row px-3 gutter; my-0.5 keeps 22px row cadence intact.
 */

// WHY no "use client": pure presentational — zero props, zero state.
export function MetricGroupDivider() {
  return <div className="h-[1px] bg-border/30 mx-3 my-0.5" />;
}
