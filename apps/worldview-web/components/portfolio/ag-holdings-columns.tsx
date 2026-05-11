/**
 * components/portfolio/ag-holdings-columns.tsx — AG Grid ColDef array for the
 * portfolio holdings table (PLAN-0071 Phase 6).
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
 * COLUMN ORDER:
 *   TICKER (pinned-left) | NAME | QTY | AVG COST | CURRENT |
 *   DAY $ | DAY % | P&L $ | P&L % | VALUE | WEIGHT | SECTOR
 *
 * WHO USES IT: components/portfolio/SemanticHoldingsTable.tsx
 */

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "./holdings-columns";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatPercentUnsigned } from "@/lib/utils";
import { formatStalenessAwarePrice, fmtPnl } from "./holdings-columns";

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

export const HOLDINGS_AG_COL_WIDTHS: Record<string, number> = {
  ticker: 80,
  name: 130,
  qty: 80,
  avgCost: 90,
  current: 90,
  dayChange: 90,
  dayChangePct: 80,
  pnl: 100,
  pnlPct: 80,
  value: 100,
  weight: 110,
  sector: 110,
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
    cellRenderer: TickerCellRenderer,
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

  // ── VALUE — sortable ────────────────────────────────────────────────────────
  {
    colId: "value",
    headerName: "VALUE",
    sortable: true,
    width: HOLDINGS_AG_COL_WIDTHS.value,
    valueGetter: (params) => params.data?.value ?? 0,
    cellRenderer: ValueCellRenderer,
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
];
