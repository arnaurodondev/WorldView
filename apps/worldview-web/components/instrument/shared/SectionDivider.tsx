/**
 * components/instrument/shared/SectionDivider.tsx — 1px row break inside grids
 *
 * WHY THIS EXISTS: metric grids are 3-col CSS grids. To separate logical
 * groups (Valuation / Profitability / …) without breaking the grid we render
 * a 1px row that col-spans all 3 columns. Optional label titles the next
 * group. WHO USES IT: FlatMetricsGrid, MetricsTable, OverviewSidebar.
 * DATA SOURCE: Pure presentational primitive.
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.11 (Section label row).
 * TARGET READER: junior Next.js dev. `col-span-3` is critical — without it
 * the divider only fills column 1 instead of the whole row.
 */

import type { ReactNode } from "react";

interface SectionDividerProps {
  /** Optional uppercase group label (e.g. "VALUATION"). */
  readonly label?: string;
}

export function SectionDivider({ label }: SectionDividerProps): ReactNode {
  return (
    <>
      <div className="h-[1px] bg-border/30 col-span-3" />
      {label ? (
        <div className="col-span-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-muted-foreground/50">{label}</div>
      ) : null}
    </>
  );
}
