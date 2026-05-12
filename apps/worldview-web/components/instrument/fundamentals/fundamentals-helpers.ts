/**
 * components/instrument/fundamentals/fundamentals-helpers.ts — Shared color helpers
 *
 * WHY EXTRACTED: getMetricClass and getMarginClass are used by both FundamentalsTab
 * (the orchestrator) and FundamentalsMetricsGrid (the grid sub-component). Placing
 * them in a shared module avoids duplication and keeps the import graph clean.
 *
 * WHY these thresholds: Bloomberg/Finviz color-code metrics so analysts can scan
 * a dense grid and spot outliers without reading every number. Red/amber/green
 * traffic-light encoding is the finance industry standard.
 */

/**
 * getMetricClass — returns a Tailwind text-color class based on numeric thresholds
 *
 * WHY null-safe: The Fundamentals type has many nullable fields (data may not be
 * available for ETFs, SPACs, or recently listed instruments). Missing data must
 * always render as "—" in muted text, never crash.
 *
 * @param value      The raw numeric value to evaluate (null → muted fallback)
 * @param greenBelow If non-null, values BELOW this threshold are colored green
 * @param redAbove   If non-null, values ABOVE this threshold are colored red
 *                   Values between greenBelow and redAbove are amber (cautionary)
 */
export function getMetricClass(
  value: number | null,
  greenBelow: number | null,
  redAbove: number | null,
): string {
  if (value == null) return "text-muted-foreground";
  // WHY check redAbove first: it's the stronger signal (analyst concern > praise)
  if (redAbove != null && value > redAbove) return "text-negative";
  if (greenBelow != null && value < greenBelow) return "text-positive";
  // Amber = in-between — not great, not terrible; Tailwind's amber-400 in dark mode
  // WHY text-warning not text-amber-400: --warning (#F59E0B) is the design system
  // token for cautionary signals. Using raw Tailwind amber-400 bypasses the token
  // and breaks if the warning color changes in globals.css.
  return "text-warning";
}

/**
 * getMarginClass — color P&L margin ratios (higher is better)
 *
 * WHY separate from getMetricClass: margins are "higher is better" (the opposite
 * direction from P/E or debt ratios). Separating avoids negating thresholds everywhere.
 *
 * @param value        Raw decimal margin (0.45 = 45%)
 * @param greenAbove   Values ABOVE this are green (good margin)
 * @param redBelow     Values BELOW this are red (poor margin)
 */
export function getMarginClass(
  value: number | null,
  greenAbove: number | null,
  redBelow: number | null,
): string {
  if (value == null) return "text-muted-foreground";
  if (greenAbove != null && value > greenAbove) return "text-positive";
  if (redBelow != null && value < redBelow) return "text-negative";
  // WHY text-warning not text-amber-400: --warning (#F59E0B) is the design system
  // token for cautionary signals. Using raw Tailwind amber-400 bypasses the token
  // and breaks if the warning color changes in globals.css.
  return "text-warning";
}
