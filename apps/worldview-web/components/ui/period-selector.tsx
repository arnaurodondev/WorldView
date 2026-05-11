/**
 * components/ui/period-selector.tsx — Pill-row period selector
 *
 * WHY THIS EXISTS: Several widgets (sector heatmap, equity curve, premarket
 * movers) show a small row of period chips (1D / 1W / 1M etc.). Every one
 * had its own copy of the same Tailwind class string. Centralising here
 * means a styling change to "active" state propagates everywhere at once.
 *
 * VARIANT NOTE: This is the "compact" pill style — 9px uppercase mono on
 * primary/20 active background. Larger period selectors (3M/6M/1Y rows on
 * detail charts) can render their own buttons; this one is for dense widgets.
 *
 * WHO USES IT: Wave D consumers (T-D-4-04). Existing call sites should be
 * migrated as they are touched.
 */

// WHY no "use client": stateless — the parent owns the selected value and
// the change handler. No hooks or browser APIs here.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface PeriodSelectorProps<P extends string = string> {
  /** Period choices, e.g. ["1D", "1W", "1M"]. */
  periods: readonly P[];
  /** Currently selected period (must be one of `periods`). */
  selected: P;
  /** Called with the new period when the user clicks a pill. */
  onSelect: (p: P) => void;
  /** Optional accessible label for the group; defaults to "Period". */
  ariaLabel?: string;
  /** Optional extra Tailwind classes for the wrapper. */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PeriodSelector<P extends string>({
  periods,
  selected,
  onSelect,
  ariaLabel = "Period",
  className,
}: PeriodSelectorProps<P>): ReactNode {
  return (
    // WHY role="group" + aria-label: gives screen-reader users context for
    // the row of buttons (otherwise they read as a stream of bare period
    // names with no semantic grouping).
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn("flex gap-px", className)}
    >
      {periods.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onSelect(p)}
          aria-pressed={p === selected}
          className={cn(
            // WHY px-1.5 text-[9px] uppercase mono: matches the existing
            // SectorHeatmapWidget period chips; keeps the row compact (~24px
            // wide per pill) so it fits in dense widget headers.
            "px-1.5 font-mono text-[9px] uppercase tracking-[0.04em] transition-colors",
            // WHY primary/20 (not /15 or /30): /20 is the canonical "active
            // toggle" tint across the app — see DESIGN_SYSTEM.md tokens.
            p === selected
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {p}
        </button>
      ))}
    </div>
  );
}
