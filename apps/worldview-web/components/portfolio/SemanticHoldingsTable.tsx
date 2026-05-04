/**
 * components/portfolio/SemanticHoldingsTable.tsx — 12-column holdings table with sort
 *
 * WHY THIS EXISTS: The portfolio holdings table is the most data-critical surface
 * for a portfolio manager. Twelve columns give enough data to make re-balancing
 * decisions without navigating to the instrument detail page.
 *   Ticker | Name | Qty | Avg Cost | Current | Day$ | Day% | P&L$ | P&L% | Value | Weight | Sector
 *
 * WHY click-to-sort: fixed row order is inconvenient for large portfolios.
 * Sorting by P&L$ immediately shows biggest winners/losers. Bloomberg PORT default.
 *
 * PLAN-0059 F-1 — Migrated to DataTable primitive. Column definitions extracted
 * to holdings-columns.tsx. ActionContextMenu preserved via DataTable rowWrapper prop.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9
 * DESIGN REFERENCE: PLAN-0044 Wave 2
 */

"use client";
// WHY "use client": uses useRouter (row-click navigation), useState (sort),
// useSearchParams + useEffect (URL sort persistence — F-P-025).

import { useState, useEffect, useMemo, useCallback } from "react";
import { type SetStateAction } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { DataTable } from "@/components/ui/data-table";
import type { SortingState } from "@tanstack/react-table";
import { ActionContextMenu } from "@/components/ui/context-menu";
import type { HoldingRowContext } from "@/lib/command-actions";
import { holdingsColumns, type EnrichedHoldingRow } from "./holdings-columns";
import { fmtPnl } from "./holdings-columns";
import type { Holding } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SemanticHoldingsTableProps {
  holdings: Holding[];
  /** Live quotes keyed by instrument_id */
  quotes: Record<string, {
    price: number;
    change: number;
    change_pct: number;
    freshness_status?: string;
  }>;
  /** GICS sector per instrument_id (loaded lazily from fundamentals) */
  sectors?: Record<string, string | null>;
  /** Total portfolio market value — used to compute Weight column */
  totalValue: number;
}

// ── Sort types ─────────────────────────────────────────────────────────────────

type SortCol = "qty" | "dayChange" | "dayChangePct" | "pnl" | "pnlPct" | "value" | "weight";
type SortDir = "asc" | "desc";

interface SortState {
  col: SortCol;
  dir: SortDir;
}

// Valid SortCol values — used to guard against malformed URL params.
const VALID_SORT_COLS: SortCol[] = [
  "qty", "dayChange", "dayChangePct", "pnl", "pnlPct", "value", "weight",
];

// ── SemanticHoldingsTable ────────────────────────────────────────────────────

export function SemanticHoldingsTable({
  holdings,
  quotes,
  sectors,
  totalValue,
}: SemanticHoldingsTableProps) {
  const router = useRouter();
  // F-P-025 (PLAN-0051 W6): persist sort to the URL so the user can
  // share a link like /portfolio?sort=pnl&dir=desc. URL-backed state
  // also survives tab switches (e.g., Holdings → Transactions → Holdings).
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Read initial sort from URL params; fall back to the trader-friendly
  // default (largest positions first by VALUE).
  const initialSort: SortState = (() => {
    const col = searchParams?.get("sort") as SortCol | null;
    const dir = searchParams?.get("dir") as SortDir | null;
    if (col && VALID_SORT_COLS.includes(col) && (dir === "asc" || dir === "desc")) {
      return { col, dir };
    }
    return { col: "value", dir: "desc" };
  })();

  // WHY default DESC by value: traders most care about their largest positions.
  const [sortState, setSortState] = useState<SortState>(initialSort);

  // F-P-025: write sort changes back to the URL via router.replace (not push —
  // we don't want a back-button entry for every sort click).
  useEffect(() => {
    if (!searchParams || !pathname) return;
    const currentCol = searchParams.get("sort");
    const currentDir = searchParams.get("dir");
    if (currentCol === sortState.col && currentDir === sortState.dir) return;
    const next = new URLSearchParams(searchParams.toString());
    next.set("sort", sortState.col);
    next.set("dir", sortState.dir);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }, [sortState, searchParams, pathname, router]);

  // ── Bridge: SortState ↔ TanStack SortingState ───────────────────────────
  // DataTable uses SortingState = { id: string; desc: boolean }[].
  // We keep our SortState as source-of-truth (for URL sync) and derive
  // the TanStack representation for the controlled sort prop.
  const tanStackSorting: SortingState = useMemo(
    () => [{ id: sortState.col, desc: sortState.dir === "desc" }],
    [sortState],
  );

  // When DataTable fires onSortingChange (user clicked a column header),
  // convert the new SortingState back into our SortState and update it.
  // The useEffect above then syncs the new sort to the URL.
  const handleSortingChange = useCallback(
    (updater: SetStateAction<SortingState>) => {
      const next = typeof updater === "function" ? updater(tanStackSorting) : updater;
      if (next.length === 0) {
        // TanStack clears all sorts when the user clicks an already-sorted column
        // a third time. Fall back to the default sort.
        setSortState({ col: "value", dir: "desc" });
      } else {
        const { id, desc } = next[0];
        setSortState({ col: id as SortCol, dir: desc ? "desc" : "asc" });
      }
    },
    [tanStackSorting],
  );

  // F-P-016 (PLAN-0051 W6): empty-state copy — Title + Body explanation.
  if (holdings.length === 0) {
    return (
      <InlineEmptyState message="No holdings yet. Connect a brokerage or use Add Position to start tracking your book." />
    );
  }

  // F-208 (QA iter-2): all-zero positions = broker sync returned nothing.
  // Render a deliberate message instead of a table of 17 zero rows.
  const allZeroQty = holdings.every((h) => Number(h.quantity) === 0);
  if (allZeroQty) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-8 px-4 text-center">
        <div className="text-[12px] font-medium text-foreground">
          No active positions reported
        </div>
        <div className="text-[11px] text-muted-foreground max-w-md">
          Your broker reported zero quantity for every holding. This can happen
          right after a sync if the brokerage feed is empty. Try resyncing your
          broker connection — if the problem persists the portfolio data may
          need to be repaired by an operator.
        </div>
      </div>
    );
  }

  // ── Enrich rows ───────────────────────────────────────────────────────────
  // WHY pre-compute (not inside cell): DataTable's getSortedRowModel uses
  // accessorFn to obtain the sort value. The accessorFn on each ColumnDef
  // reads `row.value`, `row.pnl`, etc. — fields on EnrichedHoldingRow.
  // Pre-enriching once avoids repeated arithmetic in the column accessors.
  let totalPnl = 0;
  let totalPnlCost = 0;

  const enrichedRows: EnrichedHoldingRow[] = holdings.map((h) => {
    const quote = quotes[h.instrument_id];
    const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
    const freshness = quote?.freshness_status;
    const value = livePrice * h.quantity;
    const pnl = (livePrice - h.average_cost) * h.quantity;
    const pnlPct =
      h.average_cost > 0
        ? ((livePrice - h.average_cost) / h.average_cost) * 100
        : 0;
    const weight = totalValue > 0 ? (value / totalValue) * 100 : 0;
    const sector = sectors?.[h.instrument_id] ?? null;
    const dayChange = quote?.change ?? null;
    const dayChangePct = quote?.change_pct ?? null;
    const dayChangeValue = dayChange != null ? dayChange * h.quantity : null;

    totalPnl += pnl;
    totalPnlCost += h.average_cost * h.quantity;

    return { h, livePrice, freshness, value, pnl, pnlPct, weight, sector, dayChange, dayChangePct, dayChangeValue };
  });

  const totalPnlPct = totalPnlCost > 0 ? (totalPnl / totalPnlCost) * 100 : 0;

  return (
    <div className="overflow-auto flex flex-col">
      {/*
       * WHY DataTable (not raw <table>): provides multi-column sort, sticky header,
       * column resize, and copy-as-TSV. Column defs and cell renderers live in
       * holdings-columns.tsx for isolated testing.
       *
       * WHY rowWrapper: ActionContextMenu is registry-driven (uses useContextMenuActions()
       * hook). It cannot be expressed as a static DataTableContextMenuItem[] array —
       * the registry reads the current path and row context at render time to filter
       * and group ~30 actions. rowWrapper preserves the exact ActionContextMenu
       * integration from PLAN-0059 F-3 without modification.
       */}
      <DataTable
        columns={holdingsColumns}
        data={enrichedRows}
        getRowId={(row) => row.h.holding_id}
        density="compact"
        sorting={tanStackSorting}
        onSortingChange={handleSortingChange}
        onRowClick={(row) =>
          router.push(`/instruments/${encodeURIComponent(row.h.entity_id)}`)
        }
        rowWrapper={(row, node) => {
          // Build the row context for the action registry.
          // WHY typed as HoldingRowContext: we know at compile time this is a
          // holdings table row. The full context allows actions like "Sell" to
          // gate on row.kind and "Copy Ticker" to read row.ticker.
          const ctx: HoldingRowContext = {
            kind: "holding",
            holdingId: row.h.holding_id,
            portfolioId: row.h.portfolio_id,
            instrumentId: row.h.instrument_id,
            entityId: row.h.entity_id,
            ticker: row.h.ticker,
            name: row.h.name,
          };
          return <ActionContextMenu key={row.h.holding_id} row={ctx}>{node}</ActionContextMenu>;
        }}
      />

      {/* ── Totals footer ──────────────────────────────────────────────────── */}
      {/* WHY outside DataTable: totals are a summary strip across all rows, not
          a data row. DataTable rows map to EnrichedHoldingRow entities; the
          totals strip has a different role and a different visual treatment
          (border-t-2, condensed text, font-semibold). */}
      <div className="flex h-[22px] items-center border-t-2 border-border">
        {/* Left columns spacer (TICKER + NAME + QTY + AVG COST + CURRENT + DAY$ + DAY%)
            WHY w-[640px]: sum of the 7 data columns = 80+130+80+90+90+90+80 = 640px.
            Previously 560px (off by 80px), causing TOTAL label to misalign with P&L/Value. */}
        <div className="shrink-0 w-[640px] px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TOTAL
        </div>

        {/* Total P&L $ */}
        <div
          className={cn(
            "shrink-0 w-[100px] px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
            totalPnl >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {fmtPnl(totalPnl)}
        </div>

        {/* Total P&L % */}
        <div
          className={cn(
            "shrink-0 w-[80px] px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
            totalPnlPct >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {/* F-501 fix: formatPercent already signs; no extra ternary. */}
          {formatPercent(totalPnlPct / 100)}
        </div>

        {/* Total Value */}
        <div className="shrink-0 w-[100px] px-2 font-mono text-[11px] tabular-nums text-foreground text-right font-semibold">
          {formatPrice(totalValue)}
        </div>
      </div>
    </div>
  );
}
