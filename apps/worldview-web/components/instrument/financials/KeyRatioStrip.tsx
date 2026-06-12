/**
 * components/instrument/financials/KeyRatioStrip.tsx — top-of-tab ratio strip
 * (Wave-2 Financials redesign, scope item 1).
 *
 * WHY THIS EXISTS: Bloomberg/Finviz both open their fundamentals surfaces
 * with a single horizontal band of the headline ratios — the numbers an
 * analyst checks before deciding whether to read further. Previously the
 * Financials tab opened straight into the 39-cell DenseMetricsGrid, which
 * is comprehensive but has no hierarchy: nothing told the eye where to
 * start. The strip IS that hierarchy — 12 headline cells, one row, always
 * above the fold, with the sidebar visible to its right.
 *
 * WHY 12 CELLS / WHY THESE: one cell per "first question" an analyst asks —
 * size (MKT CAP), valuation (P/E, FWD P/E, EV/EBITDA, P/S), quality (ROE,
 * NET MGN), momentum (REV YOY), cash (FCF), income (DIV YLD), risk (BETA,
 * D/E). Everything here ALSO appears in the DenseMetricsGrid below — that
 * is deliberate (terminal convention: the strip is the at-a-glance copy,
 * the grid is the reference), not duplication by accident.
 *
 * WHY MetricCell primitive (no fork): identical label-above-value structure
 * to the Quote tab strips; forking would fragment the typography pair.
 *
 * WHO USES IT: FinancialsTab.tsx — the first element of the tab, full width.
 * DATA SOURCE: fundamentals + snapshot props (already fetched by
 *   useFinancialsTabData — zero additional requests).
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §2 (tokens), ADR-F-15 (mono).
 */

// WHY no "use client": pure presentational — receives all data as props.

import { MetricCell } from "@/components/primitives/MetricCell";
import { formatMarketCap, formatPercent, formatRatio } from "@/lib/utils";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface KeyRatioStripProps {
  readonly fundamentals: Fundamentals | null;
  readonly snapshot: FundamentalsSnapshot | null;
}

// ── Colour helpers ───────────────────────────────────────────────────────────
// Mirrors DenseMetricsGrid's intent thresholds so the SAME metric never shows
// two different colours on one screen (strip vs grid must agree).

type CellColor = "positive" | "negative" | "warning" | "muted" | "default";

/** Sign-based intent: gains teal, losses red, null muted. */
function signColor(v: number | null | undefined): CellColor {
  if (v == null) return "muted";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "default";
}

/** P/E heuristic: <20 cheap (teal), >35 rich (red), else caution amber. */
function peColor(pe: number | null | undefined): CellColor {
  if (pe == null) return "muted";
  if (pe > 35) return "negative";
  if (pe < 20) return "positive";
  return "warning";
}

/** D/E heuristic: ≤0.5 conservative (teal), >2 levered (red). */
function deColor(de: number | null | undefined): CellColor {
  if (de == null) return "muted";
  if (de > 2) return "negative";
  if (de <= 0.5) return "positive";
  return "default";
}

const DASH = "—";

function fmt(
  v: number | null | undefined,
  f: (n: number | null | undefined) => string,
): string {
  return v == null ? DASH : f(v);
}

// ── Component ────────────────────────────────────────────────────────────────

export function KeyRatioStrip({ fundamentals, snapshot }: KeyRatioStripProps) {
  // Cell config inline (not a separate constants file): each cell couples a
  // label, a formatted value and a colour intent — splitting them would
  // invite drift between the three.
  const cells: Array<{ label: string; value: string; color: CellColor }> = [
    { label: "MKT CAP", value: fmt(fundamentals?.market_cap, formatMarketCap), color: "default" },
    { label: "P/E", value: fmt(fundamentals?.pe_ratio, formatRatio), color: peColor(fundamentals?.pe_ratio) },
    { label: "FWD P/E", value: fmt(fundamentals?.forward_pe, formatRatio), color: peColor(fundamentals?.forward_pe) },
    { label: "EV/EBITDA", value: fmt(fundamentals?.ev_to_ebitda, formatRatio), color: "default" },
    { label: "P/S", value: fmt(fundamentals?.price_to_sales, formatRatio), color: "default" },
    { label: "ROE", value: fmt(fundamentals?.roe, formatPercent), color: signColor(fundamentals?.roe) },
    { label: "NET MGN", value: fmt(fundamentals?.net_margin, formatPercent), color: signColor(fundamentals?.net_margin) },
    { label: "REV YOY", value: fmt(fundamentals?.revenue_growth_yoy, formatPercent), color: signColor(fundamentals?.revenue_growth_yoy) },
    { label: "FCF", value: fmt(snapshot?.free_cash_flow, formatMarketCap), color: signColor(snapshot?.free_cash_flow) },
    { label: "DIV YLD", value: fmt(fundamentals?.dividend_yield, formatPercent), color: "default" },
    { label: "BETA", value: snapshot?.beta != null ? snapshot.beta.toFixed(2) : DASH, color: "default" },
    { label: "D/E", value: fmt(fundamentals?.debt_to_equity, formatRatio), color: deColor(fundamentals?.debt_to_equity) },
    // Exactly 12 cells — one grid column each. EPS TTM was considered and
    // dropped: it lives in the PROFITABILITY grid section + the earnings
    // panel, and a 13th cell would break the 12-col rhythm.
  ];

  return (
    // WHY a 12-col grid with divide-x (not flex + gap): equal column widths
    // keep the strip's vertical rules CONSISTENT with each other — a flex
    // layout would let long values (e.g. "$3.21T") widen their cell and
    // break the rhythm. 12 columns at every breakpoint keeps the strip a
    // single row (the redesign target is 1440×900; below ~1100px the cells
    // get tight but never wrap, which preserves the divide-x rules).
    // WHY h-[38px]: two text lines (10px label + 11px value) + breathing room;
    // taller would waste the most valuable band on the tab.
    <div
      data-testid="key-ratio-strip"
      role="row"
      aria-label="Key ratio strip"
      className="grid h-[38px] shrink-0 grid-cols-12 divide-x divide-border/60 border-b border-border bg-card"
    >
      {cells.map((c) => (
        // WHY align="left": a strip cell is read label-first (top-down), and
        // left alignment under the label scans faster than the right-aligned
        // table convention (there is no column of numbers to align against).
        <MetricCell key={c.label} label={c.label} value={c.value} color={c.color} align="left" />
      ))}
    </div>
  );
}
