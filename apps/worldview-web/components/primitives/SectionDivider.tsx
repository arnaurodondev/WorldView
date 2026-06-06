/**
 * components/primitives/SectionDivider.tsx — 1px row break inside grids
 *
 * WHY THIS EXISTS: metric grids are 3-col CSS grids. To separate logical
 * groups (Valuation / Profitability / …) without breaking the grid we render
 * a 1px row that col-spans all 3 columns. Optional label titles the next
 * group. WHO USES IT: FlatMetricsGrid, MetricsTable, OverviewSidebar — and,
 * post-F1, any per-page agent that needs a section break inside a grid.
 * DATA SOURCE: Pure presentational primitive.
 * DESIGN REFERENCE: PRD-0089 F1 §3.1 (promoted from instrument/shared/ to
 *   the cross-page primitives folder) + PRD-0088 §6.11 (Section label row).
 *
 * PRD-0089 F1 CHANGE: divider now uses `border-subtle` (--border-subtle =
 * #1E1E22) instead of the previous bg-border/30. The new token has explicit
 * subtle-row-divider semantics so any later theme change targets it directly
 * instead of nudging the generic --border token. Visual delta is small:
 * #27272A @ 30% alpha ≈ #1E1E22 — within 2 luminance points.
 */

import type { ReactNode } from "react";

interface SectionDividerProps {
  /** Optional uppercase group label (e.g. "VALUATION"). */
  readonly label?: string;
}

export function SectionDivider({ label }: SectionDividerProps): ReactNode {
  return (
    <>
      <div className="h-[1px] bg-border-subtle col-span-3" />
      {label ? (
        <div className="col-span-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/50">{label}</div>
      ) : null}
    </>
  );
}
