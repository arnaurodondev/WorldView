/**
 * components/portfolio/holdings-columns.tsx — ColumnDef array for SemanticHoldingsTable
 *
 * WHY THIS EXISTS: Extracted from SemanticHoldingsTable so the 12-column definitions
 * and their cell renderers can be unit-tested in isolation from the component's
 * sort-state, URL-sync, and ActionContextMenu wiring.
 *
 * WHY EnrichedHoldingRow (not Holding): sortable columns like VALUE, P&L$, WEIGHT
 * are computed at render time (livePrice * quantity, etc.) — not raw Holding fields.
 * DataTable needs accessorFn to sort by these computed values, so we pre-enrich
 * rows before handing them to DataTable, then expose the computed values as
 * accessorFn return values.
 *
 * WHO USES IT: SemanticHoldingsTable → DataTable primitive.
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9.
 * DESIGN REFERENCE: PLAN-0044 Wave 2; PLAN-0059 F-1.
 */

import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, formatPercentUnsigned } from "@/lib/utils";
import type { ColumnDef } from "@tanstack/react-table";
import type { Holding } from "@/types/api";

// ── EnrichedHoldingRow ────────────────────────────────────────────────────────

/**
 * EnrichedHoldingRow — pre-computed shape that SemanticHoldingsTable passes to
 * DataTable as the row data type.
 *
 * WHY pre-compute here (not in cell): accessorFn for sortable columns must
 * return a number. Computing inside cell: only lets the renderer use the value;
 * it doesn't tell TanStack Table what to sort on. Pre-enriching once before
 * DataTable avoids re-computing the same arithmetic per cell per render pass.
 */
export interface EnrichedHoldingRow {
  h: Holding;
  livePrice: number;
  freshness: string | undefined;
  value: number;
  pnl: number;
  pnlPct: number;
  weight: number;
  sector: string | null;
  dayChange: number | null;
  dayChangePct: number | null;
  /** position-level day P&L = dayChange (per share) × quantity */
  dayChangeValue: number | null;
  /**
   * PLAN-0114 W6: annualised dividend yield (ratio, e.g. 0.024 = 2.4%).
   * Injected by S9's get_holdings fan-out to S3 fundamentals. Null when
   * fundamentals data is unavailable.
   */
  annualizedDividendYield: number | null;
}

// ── Helpers (exported for tests) ──────────────────────────────────────────────

export function fmtPnl(value: number): string {
  return value >= 0 ? `+${formatPrice(value)}` : formatPrice(value);
}

export function formatStalenessAwarePrice(price: number, freshness?: string): string {
  // WHY "~" prefix: if the quote is stale (end-of-day or delayed) we add a
  // tilde so traders can instantly see that the price is not live.
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}

// ── Column definitions ────────────────────────────────────────────────────────

/**
 * holdingsColumns — 12-column ColumnDef array for the SemanticHoldingsTable.
 *
 * Column order:
 *   TICKER | NAME | QTY | AVG COST | CURRENT | DAY$ | DAY% | P&L$ | P&L% | VALUE | WEIGHT | SECTOR
 *
 * Sortable columns (via accessorFn → DataTable getSortedRowModel):
 *   QTY · DAY$ · DAY% · P&L$ · P&L% · VALUE · WEIGHT
 *
 * Non-sortable (text labels, not comparable as numbers):
 *   TICKER · NAME · AVG COST · CURRENT · SECTOR
 */
export const holdingsColumns: ColumnDef<EnrichedHoldingRow>[] = [
  // ── Non-sortable text columns ───────────────────────────────────────────────
  {
    id: "ticker",
    header: "TICKER",
    size: 80,
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-primary font-medium">
        {row.original.h.ticker}
      </span>
    ),
  },
  {
    id: "name",
    header: "NAME",
    size: 130,
    enableSorting: false,
    cell: ({ row }) => (
      <span className="text-[11px] text-foreground truncate block max-w-[120px]">
        {row.original.h.name}
      </span>
    ),
  },

  // ── Sortable numeric columns ────────────────────────────────────────────────
  {
    id: "qty",
    header: "QTY",
    // accessorFn exposes the sort value to TanStack Table's getSortedRowModel.
    accessorFn: (row) => row.h.quantity,
    size: 80,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
        {row.original.h.quantity.toLocaleString("en-US")}
      </span>
    ),
  },

  // ── Non-sortable price columns ─────────────────────────────────────────────
  {
    id: "avg_cost",
    header: "AVG COST",
    size: 90,
    enableSorting: false,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
        {formatPrice(row.original.h.average_cost)}
      </span>
    ),
  },
  {
    id: "current",
    header: "CURRENT",
    size: 90,
    enableSorting: false,
    cell: ({ row }) => {
      const { livePrice, freshness } = row.original;
      return (
        <span
          className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block"
          title={
            freshness && freshness !== "live"
              ? "Delayed or end-of-day price — live feed unavailable"
              : undefined
          }
        >
          {formatStalenessAwarePrice(livePrice, freshness)}
        </span>
      );
    },
  },

  // ── Sortable day-change columns ───────────────────────────────────────────
  {
    id: "dayChange",
    header: "DAY $",
    accessorFn: (row) => row.dayChangeValue ?? 0,
    size: 90,
    cell: ({ row }) => {
      const { dayChangeValue } = row.original;
      return (
        <span
          className={cn(
            "font-mono text-[11px] tabular-nums text-right w-full block",
            dayChangeValue == null
              ? "text-muted-foreground"
              : dayChangeValue >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {dayChangeValue == null ? "—" : fmtPnl(dayChangeValue)}
        </span>
      );
    },
  },
  {
    id: "dayChangePct",
    header: "DAY %",
    accessorFn: (row) => row.dayChangePct ?? 0,
    size: 80,
    cell: ({ row }) => {
      const { dayChangePct } = row.original;
      return (
        <span
          className={cn(
            "font-mono text-[11px] tabular-nums text-right w-full block",
            dayChangePct == null
              ? "text-muted-foreground"
              : dayChangePct >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {/* F-201 fix: formatPercent already prefixes "+"/"-" — drop extra ternary. */}
          {dayChangePct == null ? "—" : formatPercent(dayChangePct / 100)}
        </span>
      );
    },
  },

  // ── Sortable P&L columns ──────────────────────────────────────────────────
  {
    id: "pnl",
    header: "P&L $",
    accessorFn: (row) => row.pnl,
    size: 100,
    cell: ({ row }) => {
      const { pnl } = row.original;
      return (
        <span
          className={cn(
            "font-mono text-[11px] tabular-nums text-right w-full block",
            pnl >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {fmtPnl(pnl)}
        </span>
      );
    },
  },
  {
    id: "pnlPct",
    header: "P&L %",
    accessorFn: (row) => row.pnlPct,
    size: 80,
    cell: ({ row }) => {
      const { pnlPct } = row.original;
      return (
        <span
          className={cn(
            "font-mono text-[11px] tabular-nums text-right w-full block",
            pnlPct >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {/* F-201 fix: same double-"+" fix as DAY %. */}
          {formatPercent(pnlPct / 100)}
        </span>
      );
    },
  },
  {
    id: "value",
    header: "VALUE",
    accessorFn: (row) => row.value,
    size: 100,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
        {formatPrice(row.original.value)}
      </span>
    ),
  },

  // ── Sortable weight column ────────────────────────────────────────────────
  {
    id: "weight",
    header: "WEIGHT",
    accessorFn: (row) => row.weight,
    size: 100,
    cell: ({ row }) => {
      const { weight } = row.original;
      return (
        <div className="flex items-center gap-1.5 justify-end">
          {/* WHY w-[48px] bar: fixed width ensures all bars are on the same
              scale regardless of text length. A 33% weight bar fills 33% of 48px. */}
          <div className="w-[48px] h-[3px] rounded-[1px] bg-muted/50 shrink-0">
            <div
              className="h-full rounded-[1px] bg-primary/50"
              style={{ width: `${Math.min(weight, 100).toFixed(1)}%` }}
            />
          </div>
          {/* F-502 (iter-2): weight is allocation share (never negative) — use
              unsigned formatter so we render "31.88%" not "+31.88%". */}
          <span className="font-mono text-[11px] tabular-nums w-[36px] text-right text-muted-foreground">
            {formatPercentUnsigned(weight / 100)}
          </span>
        </div>
      );
    },
  },

  // ── Non-sortable sector label ─────────────────────────────────────────────
  {
    id: "sector",
    header: "SECTOR",
    size: 110,
    enableSorting: false,
    cell: ({ row }) => (
      <span className="text-[11px] text-muted-foreground truncate block max-w-[100px]">
        {row.original.sector ?? "—"}
      </span>
    ),
  },

  // ── PLAN-0114 W6: dividend yield ──────────────────────────────────────────
  // WHY non-sortable: yield is an instrument property, not a position metric.
  // WHY formatPercentUnsigned: yield is always non-negative — no '+' prefix.
  {
    id: "divYld",
    header: "DIV YLD",
    size: 80,
    enableSorting: false,
    cell: ({ row }) => {
      const yld = row.original.annualizedDividendYield;
      return (
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">
          {yld == null ? "—" : formatPercentUnsigned(yld)}
        </span>
      );
    },
  },
];
