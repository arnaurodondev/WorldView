/**
 * components/primitives/TableRow.tsx — 20/18px terminal-grade table row
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — every dense data grid (Holdings,
 * Screener, Tx Ledger, Financials, Watchlist, Workspace, Peer Comparison)
 * must share one row primitive so geometry stays consistent across pages.
 * Bloomberg/Refinitiv users scan many rows fast — 20px rows + 6px cell
 * padding is the canonical terminal density.
 * WHO USES IT: any table inside a `<div data-table-grid>` container.
 * DATA SOURCE: Pure presentational primitive — no data fetching.
 * DESIGN REFERENCE: PRD-0089 F1 §2.5, §3.2 (TableRow row).
 *
 * The actual row height comes from the `--row-h` CSS variable set on the
 * parent `data-table-grid` wrapper (20px default, 18px in dense mode).
 * `role="row"` is critical: the data-table-grid global rule keys off the
 * role to apply height + bottom-border.
 *
 * INTERACTIVE rows get Tier-1 affordance hover (color-only, ≤100ms) — no
 * transform/shadow/animation on the row itself.
 */

import type { ReactNode } from "react";

interface TableRowProps {
  /** Row mode: default = 20px (read from --row-h), dense = 18px. */
  readonly height?: "default" | "dense";
  /** Selected state (e.g. multi-select in Holdings / Screener). */
  readonly selected?: boolean;
  /** Whether the row reacts to hover/focus. Static header rows pass false. */
  readonly interactive?: boolean;
  readonly children: ReactNode;
}

export function TableRow({
  height = "default",
  selected = false,
  interactive = false,
  children,
}: TableRowProps): ReactNode {
  // WHY data-row-height (not a class on the row itself): the global
  // [data-table-grid] selector already wires height/border via --row-h.
  // We surface the dense variant by toggling the data-table-grid wrapper's
  // attribute to "dense" — this row primitive doesn't need its own class.
  // The explicit attribute below is documentation for inspector debugging
  // (it has no CSS effect because the grid wrapper owns the height token).
  const interactiveClass = interactive
    ? "transition-color-only duration-100 hover:bg-muted/50 focus:outline-1 focus:outline-primary focus:outline-offset-[-1px]"
    : "";
  const selectedClass = selected ? "bg-primary/10" : "";

  return (
    <div
      role="row"
      data-row-height={height}
      className={`flex items-stretch ${interactiveClass} ${selectedClass}`.trim()}
      tabIndex={interactive ? 0 : -1}
    >
      {children}
    </div>
  );
}
