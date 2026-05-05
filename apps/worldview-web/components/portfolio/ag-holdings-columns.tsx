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

function TickerCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-primary font-medium">
      {data?.h.ticker}
    </span>
  );
}

function NameCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="text-[11px] text-foreground truncate block max-w-[120px]">
      {data?.h.name}
    </span>
  );
}

function QtyCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
      {data?.h.quantity.toLocaleString("en-US") ?? "—"}
    </span>
  );
}

function AvgCostCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
      {data ? formatPrice(data.h.average_cost) : "—"}
    </span>
  );
}

function CurrentCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  if (!data) {
    return (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>
    );
  }
  return (
    <span
      className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block"
      title={
        data.freshness && data.freshness !== "live"
          ? "Delayed or end-of-day price — live feed unavailable"
          : undefined
      }
    >
      {formatStalenessAwarePrice(data.livePrice, data.freshness)}
    </span>
  );
}

function DayChangeCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  const v = data?.dayChangeValue;
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

function DayChangePctCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  const v = data?.dayChangePct;
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

function PnlCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  const v = data?.pnl ?? 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {fmtPnl(v)}
    </span>
  );
}

function PnlPctCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  const v = data?.pnlPct ?? 0;
  return (
    <span
      className={cn(
        "font-mono text-[11px] tabular-nums text-right w-full block",
        v >= 0 ? "text-positive" : "text-negative",
      )}
    >
      {formatPercent(v / 100)}
    </span>
  );
}

function ValueCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
      {data ? formatPrice(data.value) : "—"}
    </span>
  );
}

function WeightCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  const weight = data?.weight ?? 0;
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

function SectorCellRenderer({ data }: ICellRendererParams<EnrichedHoldingRow>) {
  return (
    <span className="text-[11px] text-muted-foreground truncate block max-w-[100px]">
      {data?.sector ?? "—"}
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
