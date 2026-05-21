/**
 * components/portfolio/ag-holdings-columns.tsx — AG Grid ColDef array for the
 * portfolio holdings table (PLAN-0071 Phase 6, PRD-0089 W2).
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
 * W2 COLUMN ORDER (14 cols, 1336px total):
 *   TICKER (pinned-left) | NAME | QTY | AVG COST | CURRENT |
 *   DAY $ | DAY % | SPARK | P&L $ | P&L % | VALUE | WEIGHT | SECTOR | ASSET
 *
 * WHO USES IT: components/portfolio/SemanticHoldingsTable.tsx
 */

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "./holdings-columns";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatPercentUnsigned } from "@/lib/utils";
import { formatStalenessAwarePrice, fmtPnl } from "./holdings-columns";
import { TickerLinkCellRenderer } from "./cells/TickerLink";
import { SparklineCellRenderer } from "./cells/SparklineCellRenderer";
import { AssetTypeBadgeCellRenderer } from "./cells/AssetTypeBadge";

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
// W2 spec — 14 cols summing to 1336px (design §6.2 §Appendix A).
// WHY these specific widths: TICKER is narrow (76px) because ticker symbols
// are ≤5 chars at text-[11px]. NAME gets the most space (268px) for full
// instrument names. ASSET is minimal (48px) — single-char chip.

export const HOLDINGS_AG_COL_WIDTHS: Record<string, number> = {
  ticker: 76,
  name: 268,
  qty: 78,
  avgCost: 86,
  current: 86,
  dayChange: 82,
  dayChangePct: 70,
  spark: 76,
  value: 96,
  pnl: 90,
  pnlPct: 70,
  weight: 110,
  sector: 100,
  asset: 48,
};

// ── Cell renderers ────────────────────────────────────────────────────────────

// NOTE: TickerCellRenderer removed in step 4.10. TickerLinkCellRenderer
// (imported from cells/TickerLink.tsx) handles both the link and the TOTAL
// pinned-row label via its rowPinned guard.

// NOTE: SparklineCellRendererInline removed in step 4.11.
// SparklineCellRenderer (cells/SparklineCellRenderer.tsx) is now imported above.

// NOTE: AssetTypeBadgeCellRendererInline removed in step 4.12.
// AssetTypeBadgeCellRenderer (cells/AssetTypeBadge.tsx) is now imported above.

function NameCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="text-[11px] text-muted-foreground">—</span>;
  }
  return (
    // WHY max-w-full (was max-w-[120px]): the NAME column is 268px wide.
    // A hard 120px cap clipped names at less than half the available space.
    // max-w-full lets the span fill the full column cell (F-3 bug fix).
    <span className="text-[11px] text-foreground truncate block max-w-full">
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
  if (isPinnedBottom(params)) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">—</span>;
  }
  const v = params.data?.dayChangeValue;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v == null ? "text-muted-foreground" : v >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {v == null ? "—" : fmtPnl(v)}
    </span>
  );
}

function DayChangePctCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  if (isPinnedBottom(params)) {
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">—</span>;
  }
  const v = params.data?.dayChangePct;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v == null ? "text-muted-foreground" : v >= 0 ? "text-positive" : "text-negative",
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
    return <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">—</span>;
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
// W2 order: TICKER | NAME | QTY | AVG COST | CURRENT | DAY $ | DAY % |
//           SPARK | VALUE | P&L $ | P&L % | WEIGHT | SECTOR | ASSET
// NOTE: TickerCellRenderer is replaced by TickerLinkCellRenderer in step 4.10.
//       SparklineCellRendererInline is replaced by SparklineCellRenderer in step 4.11.
//       AssetTypeBadgeCellRendererInline is replaced by AssetTypeBadgeCellRenderer in step 4.12.

export const holdingsAgColumns: ColDef<EnrichedHoldingRow>[] = [
  // ── TICKER — pinned left, not movable ──────────────────────────────────────
  {
    colId: "ticker",
    headerName: "TICKER",
    pinned: "left" as const,
    lockPinned: true,
    suppressMovable: true,
    sortable: false,
    resizable: false,
    width: HOLDINGS_AG_COL_WIDTHS.ticker,
    // WHY TickerLinkCellRenderer: step 4.10 — navigates to /instruments/{TICKER}
    // on click. The pinned-bottom guard inside TickerLinkCellRenderer renders
    // "TOTAL" for the totals footer row (same as the old TickerCellRenderer).
    cellRenderer: TickerLinkCellRenderer,
  },

  // ── NAME ───────────────────────────────────────────────────────────────────
  {
    colId: "name",
    headerName: "NAME",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.name,
    cellRenderer: NameCellRenderer,
  },

  // ── QTY — sortable ─────────────────────────────────────────────────────────
  {
    colId: "qty",
    headerName: "QTY",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.qty,
    valueGetter: (params) => params.data?.h.quantity ?? 0,
    cellRenderer: QtyCellRenderer,
  },

  // ── AVG COST ───────────────────────────────────────────────────────────────
  {
    colId: "avg_cost",
    headerName: "AVG COST",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.avgCost,
    cellRenderer: AvgCostCellRenderer,
  },

  // ── CURRENT ───────────────────────────────────────────────────────────────
  {
    colId: "current",
    headerName: "CURRENT",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.current,
    cellRenderer: CurrentCellRenderer,
  },

  // ── DAY $ — sortable ────────────────────────────────────────────────────────
  {
    colId: "dayChange",
    headerName: "DAY $",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.dayChange,
    valueGetter: (params) => params.data?.dayChangeValue ?? 0,
    cellRenderer: DayChangeCellRenderer,
  },

  // ── DAY % — sortable ────────────────────────────────────────────────────────
  {
    colId: "dayChangePct",
    headerName: "DAY %",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.dayChangePct,
    valueGetter: (params) => params.data?.dayChangePct ?? 0,
    cellRenderer: DayChangePctCellRenderer,
  },

  // ── SPARK — sparkline for 14-day close-price momentum ──────────────────────
  // WHY field="ticker": sparkline data is keyed by ticker in the AG Grid context
  // (params.context.holdingsSeries). The ticker value in params.value is the
  // lookup key for the series array. Replaced by SparklineCellRenderer in step 4.11.
  {
    colId: "spark",
    headerName: "SPARK",
    field: "h" as unknown as keyof EnrichedHoldingRow,
    sortable: false,
    suppressMovable: false,
    width: HOLDINGS_AG_COL_WIDTHS.spark,
    cellRenderer: SparklineCellRenderer,
  },

  // ── VALUE — sortable ────────────────────────────────────────────────────────
  {
    colId: "value",
    headerName: "VALUE",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.value,
    valueGetter: (params) => params.data?.value ?? 0,
    cellRenderer: ValueCellRenderer,
  },

  // ── P&L $ — sortable ────────────────────────────────────────────────────────
  {
    colId: "pnl",
    headerName: "P&L $",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.pnl,
    valueGetter: (params) => params.data?.pnl ?? 0,
    cellRenderer: PnlCellRenderer,
  },

  // ── P&L % — sortable ────────────────────────────────────────────────────────
  {
    colId: "pnlPct",
    headerName: "P&L %",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.pnlPct,
    valueGetter: (params) => params.data?.pnlPct ?? 0,
    cellRenderer: PnlPctCellRenderer,
  },

  // ── WEIGHT — sortable ───────────────────────────────────────────────────────
  {
    colId: "weight",
    headerName: "WEIGHT",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.weight,
    valueGetter: (params) => params.data?.weight ?? 0,
    cellRenderer: WeightCellRenderer,
  },

  // ── SECTOR ─────────────────────────────────────────────────────────────────
  {
    colId: "sector",
    headerName: "SECTOR",
    sortable: false,
    width: HOLDINGS_AG_COL_WIDTHS.sector,
    cellRenderer: SectorCellRenderer,
  },

  // ── ASSET — single-char asset class chip ───────────────────────────────────
  // WHY 48px: single char (E/F/B/C/O) at text-[10px] needs only ~12px content
  // width; 48px gives comfortable padding while staying minimal.
  // Replaced by AssetTypeBadgeCellRenderer in step 4.12.
  {
    colId: "asset",
    headerName: "A",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.asset,
    // WHY params.data?.assetClass (not h.asset_class): getHoldings() never
    // populates asset_class — it is always undefined at the API layer. assetClass
    // is derived in SemanticHoldingsTable.enrichedRows with an ETF/sector fallback.
    valueGetter: (params) => params.data?.assetClass ?? "",
    cellRenderer: AssetTypeBadgeCellRenderer,
  },
];
