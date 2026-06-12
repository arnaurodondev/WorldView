/**
 * components/instrument/financials/PanelHeader.tsx — uniform 24px panel header
 * (Wave-2 Financials redesign, scope item 1).
 *
 * WHY THIS EXISTS: before this redesign, every block on the Financials tab
 * hand-rolled its own header band — heights drifted between h-6 (24px),
 * h-7 (28px) and h-[var(--row-h,20px)] (20px), and label sizes drifted
 * between text-[9px]/tracking-widest and text-[10px]/tracking-[0.08em].
 * That inconsistency is exactly what reads as "sloppy" when scanning the
 * column. One component = one height (24px, the DESIGN_SYSTEM
 * --panel-header-height target for dense panels), one label treatment
 * (uppercase 10px mono, 0.08em tracking), one accent treatment (2px
 * primary-yellow left bar + muted band — the Round-1 DenseMetricsGrid
 * pattern, DESIGN_SYSTEM §6 "accent-bar section headers").
 *
 * WHO USES IT: every panel on the Financials tab — StatementsSection,
 *   PeerComparisonTable, EarningsBarChart, the three ownership tables and
 *   the KeyRatioStrip caption. (Sidebar panels keep their lighter
 *   label-level accent because they are padded blocks, not full-bleed
 *   tables — see AnalystSidebar.)
 *
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §2 (tokens), §6 (panel chrome).
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

import type { ReactNode } from "react";

export interface PanelHeaderProps {
  /** Uppercase panel label, e.g. "PEER COMPARISON". Rendered mono 10px. */
  readonly label: string;
  /**
   * Optional muted sub-caption rendered right after the label, e.g.
   * "same GICS industry · by market cap" or the shared unit ("USD, BILLIONS").
   * 9px at 60% alpha so it never competes with the label.
   */
  readonly meta?: string;
  /**
   * Optional right-aligned slot — period toggles, "View all" links, legends.
   * The caller owns the interactive element; the header owns only layout.
   */
  readonly children?: ReactNode;
}

export function PanelHeader({ label, meta, children }: PanelHeaderProps) {
  return (
    // WHY h-6 (24px) exactly: scope item 1 mandates a 24px header on every
    // panel. WHY border-l-2 border-l-primary: the yellow accent bar makes
    // section starts scannable in peripheral vision while skimming a long
    // column (Round-1 rationale, kept). bg-muted/20 tints the band so the
    // header separates from data rows even when the label is short.
    <div
      data-panel-header
      className="flex h-6 shrink-0 items-center justify-between gap-2 border-b border-border border-l-2 border-l-primary bg-muted/20 px-2"
    >
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="whitespace-nowrap font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </span>
        {meta && (
          <span className="truncate font-mono text-[9px] text-muted-foreground/60">
            {meta}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
