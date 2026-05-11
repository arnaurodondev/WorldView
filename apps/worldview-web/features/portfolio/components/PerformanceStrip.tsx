/**
 * features/portfolio/components/PerformanceStrip.tsx — Period-return chip.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the inline 30-LOC block
 * rendered the right-aligned "+0.42% (+$120)" chip below the page header.
 * Lifting it into its own component keeps the page focused on layout and
 * makes the "covered_pct < 1 → ~ prefix" rule a unit-testable contract.
 *
 * BEHAVIOR PARITY: identical loading / empty / signed-prefix / approx-prefix
 * branches as the prior inline block.
 */

"use client";
// WHY "use client": rendered by a client-component page tree. No browser
// APIs are used here directly, but inheriting "use client" avoids an
// otherwise pointless server-component round-trip for a 30-line view.

interface PerformanceData {
  return_pct: number;
  return_abs: number;
  covered_pct: number;
}

interface PerformanceStripProps {
  /** "1D" | "1W" | "1M" — surfaced in the tooltip when covered_pct === 1. */
  period: "1D" | "1W" | "1M";
  /** Performance payload from S9 `getPortfolioPerformance`. */
  performanceData: PerformanceData | undefined;
  /** True while the underlying useQuery is in flight. */
  performanceLoading: boolean;
}

export function PerformanceStrip({
  period,
  performanceData,
  performanceLoading,
}: PerformanceStripProps) {
  return (
    // WHY no period buttons here: per user request, the 1S/1W/1M chips on the
    // Holdings page header have been removed (T-B-2-07) — they were redundant
    // with EquityCurveChart's own period toggle. The KPI/performance strip is
    // locked to 1D. EquityCurveChart's 1W/1M/3M/6M/1Y/All toggle is unchanged.
    <div className="flex shrink-0 items-center justify-end border-b border-border bg-background px-3 py-1">
      {performanceLoading ? (
        <span className="font-mono text-[10px] text-muted-foreground">—</span>
      ) : performanceData ? (
        <span
          className={[
            "font-mono text-[10px] tabular-nums font-medium",
            performanceData.return_pct >= 0 ? "text-positive" : "text-negative",
          ].join(" ")}
          title={
            performanceData.covered_pct < 1
              ? `Approximate — only ${Math.round(performanceData.covered_pct * 100)}% of positions have market data`
              : `${period} portfolio return`
          }
        >
          {/* WHY "~" prefix: standard Bloomberg convention when the figure is
              an estimate (covered_pct < 100%). */}
          {performanceData.covered_pct < 0.99 && (
            <span className="text-muted-foreground">~</span>
          )}
          {performanceData.return_pct >= 0 ? "+" : ""}
          {performanceData.return_pct.toFixed(2)}%
          <span className="ml-1 text-muted-foreground/70">
            ({performanceData.return_abs >= 0 ? "+" : ""}
            ${Math.abs(performanceData.return_abs).toFixed(0)})
          </span>
        </span>
      ) : null}
    </div>
  );
}
