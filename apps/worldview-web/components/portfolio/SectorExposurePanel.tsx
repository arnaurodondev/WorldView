/**
 * SectorExposurePanel — vertical sector breakdown list for the bottom info strip.
 *
 * WHY THIS EXISTS: The horizontal SectorAllocationBar above the holdings table
 * compresses all sectors into a 10px stacked bar — UNKN dominates by area when
 * it has the largest weight. This panel shows each sector as a labelled row with
 * its exact % weight, so analysts can scan the list top-to-bottom without having
 * to hover over tiny bar segments. Moving this to the bottom strip also frees the
 * area above the holdings table to stay tight (just the bar for a quick visual).
 *
 * WHO USES IT: BottomInfoStrip (3-column grid below SemanticHoldingsTable).
 * DATA SOURCE: bySector AllocationSlice[] derived from holdings in usePortfolioData.
 * DESIGN REFERENCE: PRD-0089 W2 density pass 2026-05-21
 */

import { formatPercent } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { AllocationSlice } from "@/features/portfolio/lib/kpi";

interface SectorExposurePanelProps {
  bySector: AllocationSlice[];
  isLoading?: boolean;
}

// Compact color dots — one per sector, matches SectorAllocationBar's palette order
// so the same sector has the same color in both components.
// WHY dots (not full-width bars): full-width colored bars would compete visually
// with the colored pct badges in ContributorsStrip to the left. A small dot +
// label + pct right-aligned is the Bloomberg PORT sector list pattern.
const SECTOR_DOTS = [
  "bg-primary/70",
  "bg-primary/50",
  "bg-primary/30",
  "bg-sky-500/60",
  "bg-emerald-500/60",
  "bg-amber-500/60",
  "bg-rose-500/60",
  "bg-violet-500/60",
  "bg-muted-foreground/40",
  "bg-muted-foreground/25",
];

export function SectorExposurePanel({ bySector, isLoading }: SectorExposurePanelProps) {
  return (
    <div className="flex flex-col bg-card border-b border-border shrink-0">
      {/* Section header */}
      <div className="flex h-[22px] shrink-0 items-center border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-neutral-500">
          Sector Exposure
        </span>
      </div>

      {/* Body */}
      {isLoading ? (
        // Loading skeleton — 5 placeholder rows
        Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex h-[22px] items-center gap-2 px-3">
            <span className="font-mono text-[11px] text-muted-foreground">—</span>
          </div>
        ))
      ) : bySector.length === 0 ? (
        <div className="flex h-[22px] items-center px-3">
          <span className="font-mono text-[11px] text-muted-foreground">—</span>
        </div>
      ) : (
        bySector.map((slice, i) => (
          // WHY h-[22px]: matches the 22px row height used across the portfolio page.
          // WHY gap-2: 8px between dot, label, and weight — tight but readable at 11px.
          <div key={slice.label} className="flex h-[22px] items-center gap-2 px-3">
            {/* Color dot — 6px circle, matches the sector color in the bar above */}
            <span
              className={cn(
                "h-1.5 w-1.5 shrink-0 rounded-full",
                SECTOR_DOTS[i] ?? "bg-muted-foreground/15",
              )}
            />

            {/* Sector label — truncated to fit; "UNKNOWN" → "UNKN" would still
                be shown at full label here so analysts know exactly what it is. */}
            {/* WHY min-w-0 flex-1 truncate: prevents the label from pushing the
                pct badge off screen on long names (e.g. "Communication Services"). */}
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-neutral-100">
              {slice.label}
            </span>

            {/* Percentage weight — right-aligned, tabular nums */}
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-neutral-500">
              {formatPercent(slice.pct)}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
