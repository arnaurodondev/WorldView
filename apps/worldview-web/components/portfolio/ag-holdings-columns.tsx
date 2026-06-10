/**
 * components/portfolio/ag-holdings-columns.tsx — AG Grid ColDef array for the
 * portfolio holdings table (PLAN-0071 Phase 6, extended PLAN-0108 W4-T401).
 *
 * WHY PARALLEL FILE (not replacing holdings-columns.tsx): holdings-columns.tsx
 * drives the legacy DataTable and its unit tests. Keeping both lets the AG Grid
 * migration ship without breaking the existing test surface. holdings-columns.tsx
 * will be removed once all consumers are confirmed migrated.
 *
 * WHY valueGetter for sortable columns: AG Grid sorts by the value returned from
 * valueGetter. For computed fields (pnl, value, weight) the sortable number lives
 * on EnrichedHoldingRow, not on a flat field path. valueGetter extracts it; the
 * cellRenderer formats it for display. Same contract as TanStack's accessorFn.
 *
 * COLUMN ORDER (14-col spec, PLAN-0108 §6):
 *   1. TICKER (pinned-left) | 2. NAME | 3. QTY | 4. AVG COST | 5. LAST |
 *   6. DAY Δ$ | 7. DAY Δ% | 8. SPARK | 9. MKT VALUE |
 *   10. UNREAL $ | 11. UNREAL % | 12. WEIGHT | 13. SECTOR | 14. ASSET
 *
 * WHY SPARK at column 8 (between DAY Δ% and MKT VALUE):
 *   The sparkline belongs in the "intraday signal" cluster (DAY Δ$ and DAY Δ%).
 *   Placing it between DAY% and MKT VALUE means the eye flows naturally:
 *   "how big was today's move → what does the trend look like → what is the
 *   position worth now." It answers the question "is today's move a blip or
 *   a continuation?" before the trader looks at the absolute value.
 *
 * WHY ASSET at column 14 (last):
 *   Asset class is a stable, rarely-changing attribute — not an actionable
 *   signal most sessions. Placing it last means it doesn't interrupt the
 *   financial flow: Ticker→Name→Size→Cost→Price→Day→Trend→Value→PnL→
 *   Weight→Sector→Type. Wide-screen users see it; narrow-screen users scroll
 *   or use AG Grid's column hide.
 *
 * WHO USES IT: components/portfolio/SemanticHoldingsTable.tsx
 */

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "./holdings-columns";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatPercentUnsigned } from "@/lib/utils";
import { formatStalenessAwarePrice, fmtPnl } from "./holdings-columns";
// WHY separate imports for cell renderers: SparklineCellRenderer and
// AssetTypeCellRenderer are self-contained modules that read their data from
// the AG Grid `context` object (not from ColDef values). Importing them here
// keeps ag-holdings-columns.tsx as the single source of truth for column
// registration while the renderers remain independently testable.
import { SparklineCellRenderer } from "./cells/SparklineCellRenderer";
import { AssetTypeCellRenderer } from "./cells/AssetTypeCellRenderer";

// ── Pinned-row detection helper ───────────────────────────────────────────────
// WHY: AG Grid passes `node.rowPinned === 'bottom'` for pinnedBottomRowData rows.
// Renderers use this to switch between normal cell content and totals content.
// WHY optional chain: in Vitest/jsdom the AG Grid node object may be undefined
// because the test environment does not fully initialise the AG Grid internals.
// The optional chain makes the helper test-safe while preserving runtime behavior.
function isPinnedBottom(params: ICellRendererParams<EnrichedHoldingRow>): boolean {
  return params.node?.rowPinned === "bottom";
}

// ── Column pixel widths ───────────────────────────────────────────────────────
// Source: PLAN-0108 §6 14-column density spec.
// WHY these exact values: the sum (76+168+78+86+86+82+70+76+96+90+70+70+80+44 = 1172px)
// fits comfortably on a 1280px viewport with TICKER pinned left at 76px.
// Narrower breakpoints rely on AG Grid's column drag-to-hide or the existing
// localStorage-persisted column state (HOLDINGS_COLS_KEY).
export const HOLDINGS_AG_COL_WIDTHS: Record<string, number> = {
  ticker: 76,
  name: 168,
  qty: 78,
  avgCost: 86,
  current: 86,      // header label: LAST
  dayChange: 82,    // header label: DAY Δ$
  dayChangePct: 70, // header label: DAY Δ%
  spark: 76,        // new (W4-T401): SPARK column (SparklineCellRenderer)
  value: 96,        // header label: MKT VALUE
  pnl: 90,          // header label: UNREAL $
  pnlPct: 70,       // header label: UNREAL %
  weight: 70,
  sector: 80,
  asset: 44,        // new (W4-T401): ASSET column (AssetTypeCellRenderer)
};

// ── Cell renderers ────────────────────────────────────────────────────────────

function TickerCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // WHY pinned-row branch: the totals footer is a pinnedBottomRowData row.
  // The TICKER cell is the natural place to show the "TOTAL" label since it is
  // pinned left and always visible regardless of horizontal scroll.
  if (isPinnedBottom(params)) {
    return (
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-semibold">
        TOTAL
      </span>
    );
  }
  return (
    <span className="font-mono text-[11px] tabular-nums text-primary font-medium">
      {params.data?.h.ticker}
    </span>
  );
}

function NameCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  return (
    <span className="text-[11px] text-foreground truncate block max-w-[120px]">
      {params.data?.h.name}
    </span>
  );
}

function QtyCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">—</span>;
  }
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
      {params.data?.h.quantity.toLocaleString("en-US") ?? "—"}
    </span>
  );
}

function AvgCostCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">—</span>;
  }
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
      {params.data ? formatPrice(params.data.h.average_cost) : "—"}
    </span>
  );
}

function CurrentCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params) || !params.data) {
    return (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
    );
  }
  return (
    <span
      className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block"
      title={
        params.data.freshness && params.data.freshness !== "live"
          ? "Delayed or end-of-day price — live feed unavailable"
          : undefined
      }
    >
      {formatStalenessAwarePrice(params.data.livePrice, params.data.freshness)}
    </span>
  );
}

function DayChangeCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // R1 sprint: the pinned TOTAL row now carries the book-level day change in
  // dayChangeValue (computed by SemanticHoldingsTable). The renderer no longer
  // special-cases pinned to "—" — it renders whatever value is present, adding
  // font-semibold so the totals line reads heavier, matching the UNREAL $ and
  // MKT VALUE totals treatment. A null value (no quotes yet) still renders "—".
  const v = params.data?.dayChangeValue;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v == null ? "text-muted-foreground" : v >= 0 ? "text-positive" : "text-negative",
        isPinnedBottom(params) && "font-semibold",
      )}
    >
      {v == null ? "—" : fmtPnl(v)}
    </span>
  );
}

function DayChangePctCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // R1 sprint: same pinned-row treatment as DayChangeCellRenderer — the TOTAL
  // row carries the portfolio-level day % (day change ÷ yesterday's value).
  const v = params.data?.dayChangePct;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v == null ? "text-muted-foreground" : v >= 0 ? "text-positive" : "text-negative",
        isPinnedBottom(params) && "font-semibold",
      )}
    >
      {v == null ? "—" : formatPercent(v / 100)}
    </span>
  );
}

function PnlCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  const v = params.data?.pnl ?? 0;
  // WHY font-semibold on pinned row: the totals row is the financial summary of
  // all positions — visually heavier weight distinguishes it from individual rows.
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v >= 0 ? "text-positive" : "text-negative",
        isPinnedBottom(params) && "font-semibold",
      )}
    >
      {fmtPnl(v)}
    </span>
  );
}

function PnlPctCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  const v = params.data?.pnlPct ?? 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v >= 0 ? "text-positive" : "text-negative",
        isPinnedBottom(params) && "font-semibold",
      )}
    >
      {formatPercent(v / 100)}
    </span>
  );
}

function ValueCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-foreground text-right w-full block",
        isPinnedBottom(params) && "font-semibold",
      )}
    >
      {params.data ? formatPrice(params.data.value) : "—"}
    </span>
  );
}

function WeightCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    // R1 sprint: the TOTAL row shows the weight-column sum (≈100.00% whenever
    // every position has a price) instead of "—". This is the trader's sanity
    // check that the Weight column is internally consistent — a total that
    // drifts from 100% signals missing quotes upstream. No bar is drawn: a
    // full-width bar would just be chart noise on the totals line.
    const w = params.data?.weight ?? 0;
    return (
      <span className="font-mono text-[11px] tabular-nums text-foreground font-semibold text-right w-full block">
        {w > 0 ? formatPercentUnsigned(w / 100) : "—"}
      </span>
    );
  }
  const weight = params.data?.weight ?? 0;
  return (
    <div className="flex items-center gap-1.5 justify-end">
      {/* WHY w-[48px] bar: fixed width keeps all bars on the same scale. */}
      <div className="w-[48px] h-[3px] rounded-[1px] bg-muted/50 shrink-0">
        <div
          className="h-full rounded-[1px] bg-primary/50"
          style={{ width: `${Math.min(weight, 100).toFixed(1)}%` }}
        />
      </div>
      <span className="font-mono text-[11px] tabular-nums w-[36px] text-right text-muted-foreground">
        {formatPercentUnsigned(weight / 100)}
      </span>
    </div>
  );
}

function SectorCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  return (
    <span className="text-[11px] text-muted-foreground truncate block max-w-[100px]">
      {params.data?.sector ?? "—"}
    </span>
  );
}

// ── Column definitions ────────────────────────────────────────────────────────

export const holdingsAgColumns: ColDef<EnrichedHoldingRow>[] = [
  // ── 1. TICKER — pinned left, not movable ───────────────────────────────────
  {
    colId: "ticker",
    headerName: "TICKER",
    pinned: "left" as const,
    lockPinned: true,
    suppressMovable: true,
    sortable: false,
    resizable: false,
    width: HOLDINGS_AG_COL_WIDTHS.ticker,
    cellRenderer: TickerCellRenderer,
  },

  // ── 2. NAME ────────────────────────────────────────────────────────────────
  {
    colId: "name",
    headerName: "NAME",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.name,
    cellRenderer: NameCellRenderer,
  },

  // ── 3. QTY — sortable ──────────────────────────────────────────────────────
  {
    colId: "qty",
    headerName: "QTY",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.qty,
    valueGetter: (params) => params.data?.h.quantity ?? 0,
    cellRenderer: QtyCellRenderer,
  },

  // ── 4. AVG COST ────────────────────────────────────────────────────────────
  {
    colId: "avg_cost",
    headerName: "AVG COST",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.avgCost,
    cellRenderer: AvgCostCellRenderer,
  },

  // ── 5. LAST (was CURRENT) ─────────────────────────────────────────────────
  // WHY renamed to LAST: "LAST" is standard Bloomberg/Reuters terminal vocabulary
  // for the most recent trade price. "CURRENT" is ambiguous (current as of when?).
  // The colId stays "current" (not "last") to preserve existing localStorage
  // column-state persistence — changing the colId would cause a one-time layout
  // reset for users who have saved column state (HOLDINGS_COLS_KEY).
  {
    colId: "current",
    headerName: "LAST",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.current,
    cellRenderer: CurrentCellRenderer,
  },

  // ── 6. DAY Δ$ — sortable ──────────────────────────────────────────────────
  // WHY Δ prefix: the delta symbol is the standard shorthand for "change"
  // in financial terminals. More compact than "CHG" and universally understood
  // in an equity context (Δ price today vs yesterday's close).
  {
    colId: "dayChange",
    headerName: "DAY Δ$",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.dayChange,
    valueGetter: (params) => params.data?.dayChangeValue ?? 0,
    cellRenderer: DayChangeCellRenderer,
  },

  // ── 7. DAY Δ% — sortable ──────────────────────────────────────────────────
  {
    colId: "dayChangePct",
    headerName: "DAY Δ%",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.dayChangePct,
    valueGetter: (params) => params.data?.dayChangePct ?? 0,
    cellRenderer: DayChangePctCellRenderer,
  },

  // ── 8. SPARK — 14-day sparkline (PLAN-0108 W4-T401) ──────────────────────
  // WHY not sortable: a sparkline has no meaningful scalar sort key. The closest
  // proxy (momentum slope) doesn't exist in the current data model; adding a
  // derived slope column is a separate concern (future Analytics enhancement).
  //
  // WHY no valueGetter: SparklineCellRenderer reads holdingsSeries from AG Grid
  // context (context.holdingsSeries keyed by ticker). Putting large number arrays
  // into the value pipeline would force AG Grid to deep-clone them on every render
  // cycle — context access is O(1) pointer lookup, no cloning.
  //
  // WHY headerClass "!text-center": centres the "SPARK" header text to align
  // visually with the centred sparkline SVG below it. The ! Tailwind prefix
  // overrides AG Grid's default left-align header class.
  {
    colId: "spark",
    headerName: "SPARK",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.spark,
    headerClass: "!text-center",
    cellRenderer: SparklineCellRenderer,
  },

  // ── 9. MKT VALUE — sortable (was VALUE) ───────────────────────────────────
  // WHY renamed to MKT VALUE: "VALUE" alone is ambiguous (book value? NAV?).
  // "MKT VALUE" explicitly means the current market value of the position
  // (quantity × last price), matching prime-brokerage statement terminology.
  // colId stays "value" to preserve localStorage column state.
  {
    colId: "value",
    headerName: "MKT VALUE",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.value,
    valueGetter: (params) => params.data?.value ?? 0,
    cellRenderer: ValueCellRenderer,
  },

  // ── 10. UNREAL $ — sortable (was P&L $) ───────────────────────────────────
  // WHY renamed to UNREAL $: "P&L" is ambiguous — it encompasses both realised
  // and unrealised gains. "UNREAL $" makes it immediately clear this is the
  // open, not-yet-realised unrealised P&L. Bloomberg PORT uses "UNRL $".
  // colId stays "pnl" to preserve localStorage column state.
  {
    colId: "pnl",
    headerName: "UNREAL $",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.pnl,
    valueGetter: (params) => params.data?.pnl ?? 0,
    cellRenderer: PnlCellRenderer,
  },

  // ── 11. UNREAL % — sortable (was P&L %) ───────────────────────────────────
  // colId stays "pnlPct" to preserve localStorage column state.
  {
    colId: "pnlPct",
    headerName: "UNREAL %",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.pnlPct,
    valueGetter: (params) => params.data?.pnlPct ?? 0,
    cellRenderer: PnlPctCellRenderer,
  },

  // ── 12. WEIGHT — sortable ──────────────────────────────────────────────────
  {
    colId: "weight",
    headerName: "WEIGHT",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.weight,
    valueGetter: (params) => params.data?.weight ?? 0,
    cellRenderer: WeightCellRenderer,
  },

  // ── 13. SECTOR ─────────────────────────────────────────────────────────────
  {
    colId: "sector",
    headerName: "SECTOR",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.sector,
    cellRenderer: SectorCellRenderer,
  },

  // ── 14. ASSET — asset-class badge (PLAN-0108 W4-T401) ────────────────────
  // WHY 44px: the widest badge is "ETF" (3 chars × ~7px mono + 4px padding each
  // side) ≈ 29px. 44px gives ~7.5px whitespace per side for breathing room while
  // keeping the column as narrow as possible.
  //
  // WHY center-aligned header + cell: small chips look unanchored when
  // left-aligned — the badge floats away from the column label. Center alignment
  // bins the chip visually with the "ASSET" header text.
  //
  // WHY no valueGetter: AssetTypeCellRenderer reads context.assetClasses keyed
  // by instrument_id. Same no-clone context-read pattern as SPARK.
  //
  // WHY cellStyle object (not className): AG Grid applies cellStyle as an inline
  // style on the cell wrapper div, which controls the flex layout of the content
  // container. Without this, the AssetTypeCellRenderer's inner flex div doesn't
  // have a flex parent to centre against, and the chip drifts to the top.
  {
    colId: "asset",
    headerName: "ASSET",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.asset,
    headerClass: "!text-center",
    cellStyle: { display: "flex", alignItems: "center", justifyContent: "center" },
    cellRenderer: AssetTypeCellRenderer,
  },
];
