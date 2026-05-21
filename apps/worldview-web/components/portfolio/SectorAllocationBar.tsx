/**
 * SectorAllocationBar — 22px stacked horizontal sector bar.
 *
 * WHY THIS EXISTS: The 240px SectorAllocationPanel was overkill for the overview.
 * This 22px bar shows sector mix at a glance — exactly what a PM checks before
 * deciding to over/underweight. Replaces the taller panel on the overview page.
 * WHO USES IT: portfolio overview page, between PerformanceChartPanel and HoldingsTableChrome.
 * DATA SOURCE: bySector AllocationSlice[] derived from holdings in usePortfolioData.
 * DESIGN REFERENCE: PRD-0089 W2 §4.6
 */

import { formatPercent } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

// Fixed palette for sector segments — design system muted palette, not accent.
// WHY opacity variants (not separate hex colors): keeps the palette coherent
// with the overall terminal dark theme. Fully opaque primary would overpower
// the data rows below.
const SECTOR_COLORS = [
  "bg-primary/70",
  "bg-primary/50",
  "bg-primary/30",
  "bg-muted-foreground/40",
  "bg-muted-foreground/25",
  "bg-muted-foreground/15",
];

interface SectorAllocationBarProps {
  bySector: AllocationSlice[];
}

export function SectorAllocationBar({ bySector }: SectorAllocationBarProps) {
  if (bySector.length === 0) {
    return (
      <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Sector</span>
        <span className="ml-3 text-[11px] font-mono text-muted-foreground">—</span>
      </div>
    );
  }

  return (
    <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3 gap-2">
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground shrink-0">Sector</span>
      {/* Stacked bar — each segment proportional to pct.
          WHY overflow-hidden: segments must be clipped to the bar bounds when
          pct values don't sum to exactly 1.0 due to floating-point rounding. */}
      <div className="flex flex-1 h-[10px] overflow-hidden">
        {bySector.map((s, i) => (
          <div
            key={s.label}
            className={cn("h-full", SECTOR_COLORS[i] ?? "bg-muted-foreground/10")}
            // WHY (s.pct * 100): AllocationSlice.pct is a 0-1 fraction; CSS width expects %.
            style={{ width: `${(s.pct * 100).toFixed(2)}%` }}
            title={`${s.label}: ${formatPercent(s.pct)}`}
          />
        ))}
      </div>
      {/* Top-3 label tease — inline after bar for quick sector identification */}
      <div className="flex items-center gap-2 shrink-0">
        {bySector.slice(0, 3).map((s) => (
          <span key={s.label} className="font-mono text-[10px] text-muted-foreground tabular-nums">
            {s.label.substring(0, 4).toUpperCase()} {formatPercent(s.pct)}
          </span>
        ))}
      </div>
    </div>
  );
}
