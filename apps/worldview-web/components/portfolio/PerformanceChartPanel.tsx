/**
 * PerformanceChartPanel — 120px collapsible chart: portfolio line + SPY benchmark.
 *
 * WHY THIS EXISTS: Portfolio managers need quick trend context without navigating
 * to a full analytics page. 120px is compact enough to stay above the fold while
 * giving meaningful shape. SPY overlay (DISCUSS-10: locked, SPY-only v1) provides
 * immediate alpha/beta intuition — "am I beating the market this month?"
 * WHO USES IT: portfolio overview page, between ConcentrationSectorTeaseStrip and SectorAllocationBar.
 * DATA SOURCE:
 *   - Portfolio series: holdings-derived value history (from parent via props)
 *   - SPY benchmark: useBenchmarkSeries(period) hook (future integration)
 * DESIGN REFERENCE: PRD-0089 W2 §4.5, V10
 *
 * WHY chart is a placeholder (not lightweight-charts): PerformanceChartPanel is a
 * layout shell. Full chart integration is deferred — renders "chart · {period}" when
 * no data, keeping W2 shippable without blocking on chart library config.
 */
"use client";
// WHY "use client": useState for collapsed/period state; onClick handlers.

import { cn } from "@/lib/utils";

export type PerfPeriod = "1W" | "1M" | "3M" | "6M" | "1Y" | "All";
const PERIODS: PerfPeriod[] = ["1W", "1M", "3M", "6M", "1Y", "All"];

interface PerformanceChartPanelProps {
  period: PerfPeriod;
  onPeriodChange: (p: PerfPeriod) => void;
  /** Whether the chart is collapsed to a 28px header row. */
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function PerformanceChartPanel({
  period,
  onPeriodChange,
  collapsed = false,
  onToggleCollapse,
}: PerformanceChartPanelProps) {
  return (
    <div
      className={cn(
        "flex flex-col shrink-0 border-b border-border bg-card",
        collapsed ? "h-[28px]" : "h-[120px]",
      )}
    >
      {/* Header row: PERFORMANCE label + collapse toggle + period selector */}
      <div className="flex h-[28px] shrink-0 items-center px-3 gap-2">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground flex items-center gap-1"
          aria-label={collapsed ? "Expand performance chart" : "Collapse performance chart"}
        >
          <span>Performance</span>
          {/* WHY ▶/▼ glyph: single char, no import needed, terminal-native */}
          <span aria-hidden>{collapsed ? "▶" : "▼"}</span>
        </button>
        {/* SPY overlay always present per DISCUSS-10 lock — no toggle needed */}
        <span className="ml-1 text-[10px] text-muted-foreground">vs SPY</span>
        <div className="ml-auto flex items-center gap-0">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPeriodChange(p)}
              className={cn(
                "h-5 px-1.5 text-[10px] font-mono",
                period === p
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Chart area — only rendered when not collapsed */}
      {!collapsed && (
        <div className="flex-1 min-h-0 px-3 pb-1 flex items-center">
          {/* WHY placeholder div instead of full chart: the PerformanceChartPanel
              is a layout shell. Full chart integration (lightweight-charts) is
              deferred — renders "—" when no data. This keeps W2 shippable
              without blocking on chart library config. When useBenchmarkSeries
              and useHoldingsSeries both return data the parent passes them down. */}
          <div className="flex-1 flex items-center justify-center">
            <span className="text-[10px] font-mono text-muted-foreground">chart · {period}</span>
          </div>
        </div>
      )}
    </div>
  );
}
