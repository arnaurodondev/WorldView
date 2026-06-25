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
import { formatMarketCap, formatPercent, formatPercentUnsigned, formatRatio } from "@/lib/utils";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface KeyRatioStripProps {
  readonly fundamentals: Fundamentals | null;
  readonly snapshot: FundamentalsSnapshot | null;
}

// ── Colour helpers ───────────────────────────────────────────────────────────
// COLOUR SEMANTICS (UI roadmap 2026-06-19 item #1 / A1): teal/red are reserved
// for DIRECTIONAL values only — here just REV YOY (a rate-of-change) and FCF
// (sign matters: cash burn vs generation). Non-directional LEVELS — P/E, FWD
// P/E, ROE, NET MGN, D/E, DIV YLD, BETA — render neutral. A red P/E or a green
// margin is an editorial judgement masquerading as a direction; "cheap vs rich"
// belongs in peer-percentile heat (roadmap B3). The peColor/deColor threshold
// helpers were removed; this strip now AGREES with the neutralised grid.

type CellColor = "positive" | "negative" | "warning" | "muted" | "default";

/**
 * Sign-based intent — ONLY for directional values (REV YOY growth, FCF sign):
 * gains teal, losses red, null muted.
 */
function signColor(v: number | null | undefined): CellColor {
  if (v == null) return "muted";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
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
    // P/E + FWD P/E: non-directional valuation levels → neutral (item #1).
    { label: "P/E", value: fmt(fundamentals?.pe_ratio, formatRatio), color: "default" },
    { label: "FWD P/E", value: fmt(fundamentals?.forward_pe, formatRatio), color: "default" },
    { label: "EV/EBITDA", value: fmt(fundamentals?.ev_to_ebitda, formatRatio), color: "default" },
    { label: "P/S", value: fmt(fundamentals?.price_to_sales, formatRatio), color: "default" },
    // ROE + NET MGN: quality levels → neutral + unsigned (no "+" on a level).
    { label: "ROE", value: fmt(fundamentals?.roe, formatPercentUnsigned), color: "default" },
    { label: "NET MGN", value: fmt(fundamentals?.net_margin, formatPercentUnsigned), color: "default" },
    // REV YOY: DIRECTIONAL rate-of-change → keep teal/red + signed %.
    { label: "REV YOY", value: fmt(fundamentals?.revenue_growth_yoy, formatPercent), color: signColor(fundamentals?.revenue_growth_yoy) },
    // FCF: sign is directional (burn vs generation) → keep colour.
    { label: "FCF", value: fmt(snapshot?.free_cash_flow, formatMarketCap), color: signColor(snapshot?.free_cash_flow) },
    // DIV YLD: allocation-style level → neutral + unsigned.
    { label: "DIV YLD", value: fmt(fundamentals?.dividend_yield, formatPercentUnsigned), color: "default" },
    { label: "BETA", value: snapshot?.beta != null ? snapshot.beta.toFixed(2) : DASH, color: "default" },
    // D/E: leverage level → neutral (item #1).
    { label: "D/E", value: fmt(fundamentals?.debt_to_equity, formatRatio), color: "default" },
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
