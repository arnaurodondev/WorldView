/**
 * components/instrument/financials/MetricCell.tsx — single label/value cell for the Financials grid
 *
 * WHY THIS EXISTS: The Financials tab redesign (PRD-0088 §6.8.1 / PLAN-0090 T-C-01)
 * renders 45 fundamentals fields in a Finviz-style 3-column flat grid. Each cell is
 * a label/value pair at 22px row height. Centralising the cell layout into a single
 * component guarantees identical density, typography, and divider treatment across
 * all 45 cells — and across the 8 group-header rows — without ad-hoc styling in
 * FlatMetricsGrid.
 *
 * WHY NOT REUSE OverviewSidebarMetrics' MetricRow (in InstrumentKeyMetrics.tsx):
 * That row is a full-width row inside a 280px sidebar column. The Financials grid
 * is a 3-column layout where each cell occupies one-third of the available width;
 * the internal label/value alignment, max-width clamping, and border treatment
 * differ. Forking a dedicated MetricCell here keeps the sidebar component free
 * to evolve independently (e.g. WeekRangeBar row is a sidebar-only concern).
 *
 * WHY 22px row height (h-[22px]): Mandated by the Terminal UI v3 design system
 * (§0.1 — data row density). Every data row across the entire app uses h-[22px]
 * for consistent terminal-style density.
 *
 * WHY 10px label / 11px value with tabular-nums: §0.1 label typography (uppercase
 * 10px, 0.08em tracking, muted-foreground) + value typography (font-mono 11px
 * with tabular-nums so digits align column-wise — critical for scanning numeric
 * tables at a glance). Mirrors the screener row pattern.
 *
 * WHO USES IT: FlatMetricsGrid.tsx (this directory). Not exported beyond the
 * financials/ folder — internal grid primitive.
 *
 * DESIGN REFERENCE: docs/specs/0088-instrument-detail-page-ground-up-redesign.md §6.8.1
 */

// Pure presentational component — no client-side hooks. Kept as a server-safe
// module so it can be statically analyzed and tree-shaken.

import { cn } from "@/lib/utils";

// ── Props ───────────────────────────────────────────────────────────────────

export interface MetricCellProps {
  /**
   * Uppercase short label, e.g. "P/E", "MKT CAP", "ROE".
   * Will be rendered as-is — caller is responsible for casing/abbreviation.
   * WHY caller-controlled: some labels need bespoke casing (e.g. "P/E", "EV/EBITDA",
   * "52W HIGH") that auto-uppercasing breaks. CSS uppercase is still applied for
   * consistency with the design system but it is a no-op on already-uppercase text.
   */
  label: string;

  /**
   * Pre-formatted display value, e.g. "$3.42T", "28.7", "12.3%", "—".
   * WHY pre-formatted (not raw number): the 45 fields use a mix of formatters
   * (formatMarketCap, formatRatio, formatPercent, formatPrice, formatDate). The
   * caller knows which formatter applies; this cell only renders text. Null/missing
   * values are conventionally rendered by the caller as "—" (Bloomberg convention).
   */
  value: string;

  /**
   * Optional Tailwind class string applied to the value span. Used by callers to
   * colour code values based on thresholds — e.g. text-positive when ROE > 15%,
   * text-negative when D/E > 2. Defaults to text-foreground.
   */
  valueClass?: string;

  /**
   * When true, marks this as a "group header" row rather than a data row. Group
   * headers span the full cell width (label only, no value) and use a slightly
   * stronger style to visually segment the 8 sections (VALUATION, PROFITABILITY,
   * GROWTH, BALANCE SHEET, CASH FLOW, DIVIDENDS, OWNERSHIP, TECHNICALS).
   *
   * WHY one component for both: keeps row height (22px) identical between header
   * and data rows so the grid alignment never drifts. The alternative — separate
   * GroupHeader + DataCell components — risks subtle px-mismatches during
   * iteration. One component, one source of truth for row metrics.
   */
  isHeader?: boolean;
}

// ── Component ───────────────────────────────────────────────────────────────

export function MetricCell({
  label,
  value,
  valueClass = "text-foreground",
  isHeader = false,
}: MetricCellProps) {
  // ── Group header variant ──────────────────────────────────────────────────
  // WHY no value rendered: headers are pure section labels. The grid is laid out
  // such that headers occupy a full row (col-span-3) — see FlatMetricsGrid.
  // WHY border-b border-border (not /30): headers want a stronger divider so the
  // section break is unmistakable when scanning the grid; data rows use the
  // softer /30 hairline between rows of the same section.
  if (isHeader) {
    return (
      <div
        className="col-span-3 flex items-center h-[22px] px-2 border-b border-border bg-muted/20"
        // WHY data attribute: lets tests and visual-regression tools target headers
        // without brittle nth-child selectors.
        data-metric-cell="header"
      >
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          {label}
        </span>
      </div>
    );
  }

  // ── Data cell variant ─────────────────────────────────────────────────────
  // WHY flex (not grid-cols-[1fr_auto]): flex with flex-1 + text-right matches
  // the proven row layout from OverviewSidebarMetrics.MetricRow. Keeps label
  // truncation behaviour (truncate on overflow) trivial.
  // WHY border-b border-border/30: hairline divider between rows in the same
  // section. Last-row-of-section borders are suppressed by the group header
  // following them (which has its own border-b border-border).
  return (
    <div
      className="flex items-center h-[22px] px-2 border-b border-border/30"
      data-metric-cell="data"
    >
      {/* Label — uppercase 10px per §0.1 label typography. truncate guards against
          accidentally long labels overflowing into the value area. */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
        {label}
      </span>
      {/* Value — monospace tabular-nums per §0.1 data value typography.
          max-w clamp + truncate prevents extreme values (e.g. "12,345,678,901")
          from pushing the column wider than its grid cell. */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums truncate max-w-[60%] text-right",
          valueClass,
        )}
      >
        {value}
      </span>
    </div>
  );
}
