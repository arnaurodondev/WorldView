/**
 * components/portfolio/SemanticHoldingsTable.tsx — 14-column holdings table
 *
 * WHY THIS EXISTS: The portfolio holdings table is the most data-critical surface
 * for a portfolio manager. Fourteen columns give enough data to make re-balancing
 * decisions without navigating to the instrument detail page.
 *   Ticker | Name | Qty | Avg Cost | Current | Day$ | Day% | SPARK | P&L$ | P&L% | Value | Weight | Sector | Asset
 *
 * PLAN-0071 Phase 6 — AG Grid migration:
 *   - DataTable replaced with AgGridBase (ag-grid-community v35).
 *   - TICKER column pinned left (lockPinned + suppressMovable on the ColDef).
 *   - Column definitions moved to ag-holdings-columns.tsx.
 *   - AG Grid handles client-side sort internally. URL-backed sort (F-P-025) is
 *     preserved: initial sort read from URL params and applied via applyColumnState
 *     in handleGridReady; subsequent sort changes written to URL via onSortChanged.
 *   - Column state (width, order, visibility) persisted to localStorage under
 *     HOLDINGS_COLS_KEY. Restored on mount via handleGridReady.
 *   - Cell flash (flashCells) fires on live quote changes, highlighting the rows
 *     and columns that updated.
 *   - ActionContextMenu replaced with a floating custom menu driven by
 *     useContextMenuActions. The floating menu is positioned at mouse coordinates
 *     from CellContextMenuEvent and closed on outside click.
 *   - Totals footer uses AG Grid pinnedBottomRowData (BP-455 fix). The former
 *     hardcoded-pixel-width sibling <div> footer was removed; the pinned row
 *     stays in sync with column widths and TICKER pin automatically.
 *
 * PRD-0089 W2 §4.8 — density lock:
 *   - rowHeight=20 (was 28) — fits more positions above the fold.
 *   - SPARK + ASSET columns added in §4.9 via ag-holdings-columns.tsx.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9
 * DESIGN REFERENCE: PLAN-0044 Wave 2, PLAN-0059 F-1, PLAN-0071 Phase 6, PRD-0089 W2
 */

"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { AgGridBase } from "@/components/ui/ag-grid/AgGridBase";
import { holdingsAgColumns } from "./ag-holdings-columns";
import { useContextMenuActions } from "@/hooks/useContextMenuActions";
import type { HoldingRowContext, ActionContext } from "@/lib/command-actions";
import type { EnrichedHoldingRow } from "./holdings-columns";
import type { Holding } from "@/types/api";
import type {
  GridApi,
  GridReadyEvent,
  CellContextMenuEvent,
  SortChangedEvent,
  IRowNode,
} from "ag-grid-community";

// ── Constants ─────────────────────────────────────────────────────────────────

// WHY v2 (was "worldview-holdings-cols"): W2 adds SPARK + ASSET columns that don't
// exist in the v1 persisted column state. Loading a v1 state would position the new
// columns in wrong places or hide them entirely. Bumping the key creates a new
// localStorage namespace so stale v1 state is ignored automatically on first load.
const HOLDINGS_COLS_KEY = "holdings.col-state.v2";

// Valid AG Grid sort column IDs for holdings (guards against malformed URL params).
const VALID_SORT_COL_IDS = new Set([
  "qty", "dayChange", "dayChangePct", "pnl", "pnlPct", "value", "weight",
]);

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
  /**
   * 14-day OHLCV close-price series keyed by ticker — fed to SparklineCellRenderer
   * via AG Grid context. WHY context (not a per-row prop): AG Grid ColDefs are
   * static objects; passing dynamic data per-row requires context injection.
   * The context object reference only changes when holdingsSeries changes, so
   * it does not cause spurious re-renders of unchanged rows.
   */
  holdingsSeries?: Record<string, number[]>;
}

// ── Context menu overlay ──────────────────────────────────────────────────────

interface CtxMenuState {
  row: HoldingRowContext;
  x: number;
  y: number;
}

// ── SemanticHoldingsTable ─────────────────────────────────────────────────────

export function SemanticHoldingsTable({
  holdings,
  quotes,
  sectors,
  totalValue,
  holdingsSeries,
}: SemanticHoldingsTableProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // ── AG Grid API ref ───────────────────────────────────────────────────────
  const gridApiRef = useRef<GridApi<EnrichedHoldingRow> | null>(null);

  // ── Context menu state ────────────────────────────────────────────────────
  const [ctxMenu, setCtxMenu] = useState<CtxMenuState | null>(null);

  // useContextMenuActions must be called unconditionally at the top.
  // When ctxMenu is null, row is undefined → groups will be empty.
  const { groups: ctxGroups } = useContextMenuActions(ctxMenu?.row);

  // Build ActionContext for action.run() calls.
  const actionCtx: ActionContext = useMemo(
    () => ({
      row: ctxMenu?.row,
      navigate: (path: string) => router.push(path),
      toast: (message: string, opts?: { description?: string }) => {
        toast(message, opts);
      },
    }),
    [ctxMenu?.row, router],
  );

  // Close context menu on click outside.
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [ctxMenu]);

  // ── Cell flash on live price updates ─────────────────────────────────────
  const prevQuotesRef = useRef<typeof quotes>({});
  useEffect(() => {
    const api = gridApiRef.current;
    if (!api) return;

    const changedIds = Object.keys(quotes).filter(
      (id) => quotes[id]?.price !== prevQuotesRef.current[id]?.price,
    );
    prevQuotesRef.current = quotes;
    if (changedIds.length === 0) return;

    const rowNodes: IRowNode<EnrichedHoldingRow>[] = [];
    api.forEachNode((node) => {
      if (node.data && changedIds.includes(node.data.h.instrument_id)) {
        rowNodes.push(node);
      }
    });
    if (rowNodes.length > 0) {
      api.flashCells({
        rowNodes,
        columns: ["current", "dayChange", "dayChangePct", "pnl", "pnlPct", "value"],
        flashDuration: 500,
      });
    }
  }, [quotes]);

  // ── AG Grid event handlers ────────────────────────────────────────────────

  const handleGridReady = useCallback(
    (params: GridReadyEvent<EnrichedHoldingRow>) => {
      gridApiRef.current = params.api;

      // P6-2: Restore saved column state (width, order, visibility) from localStorage.
      try {
        const saved = localStorage.getItem(HOLDINGS_COLS_KEY);
        if (saved) {
          params.api.applyColumnState({
            state: JSON.parse(saved) as Parameters<GridApi["applyColumnState"]>[0]["state"],
            applyOrder: true,
          });
        }
      } catch { /* ignore corrupted state */ }

      // F-P-025: restore URL-backed sort on mount.
      const col = searchParams?.get("sort");
      const dir = searchParams?.get("dir");
      if (col && VALID_SORT_COL_IDS.has(col) && (dir === "asc" || dir === "desc")) {
        params.api.applyColumnState({
          state: [{ colId: col, sort: dir }],
          defaultState: { sort: null },
        });
      } else {
        // Default: largest positions first.
        params.api.applyColumnState({
          state: [{ colId: "value", sort: "desc" }],
          defaultState: { sort: null },
        });
      }
    },
    // searchParams is stable on mount; this should not re-run on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // F-P-025: write sort changes back to URL (router.replace = no back-button entry).
  const handleSortChanged = useCallback(
    (event: SortChangedEvent<EnrichedHoldingRow>) => {
      if (!searchParams || !pathname) return;
      const state = event.api.getColumnState();
      const sorted = state.find((s) => s.sort != null);
      const next = new URLSearchParams(searchParams.toString());
      if (sorted?.sort) {
        next.set("sort", sorted.colId);
        next.set("dir", sorted.sort);
      } else {
        next.delete("sort");
        next.delete("dir");
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [router, searchParams, pathname],
  );

  // P6-2: Persist full column state to localStorage on any column change.
  // MED-023: wrap in QuotaExceededError guard — localStorage fill-up (common
  // when many workspaces + workspace panels are persisted) must not crash the
  // UI. Columns still sort/reorder in-session; the layout just won't survive
  // a page refresh. We log a console.warn so devs can detect the condition.
  const handleColumnStateChanged = useCallback(() => {
    const api = gridApiRef.current;
    if (!api) return;
    try {
      localStorage.setItem(HOLDINGS_COLS_KEY, JSON.stringify(api.getColumnState()));
    } catch (e) {
      if (e instanceof DOMException && e.name === "QuotaExceededError") {
        // Storage full — layout works in-session but won't persist across
        // page refreshes. Silent failure is acceptable for column layout;
        // logging warns devs without interrupting the trader's workflow.
        console.warn("[AG Grid] Column layout persistence failed: storage quota exceeded");
      }
      // Re-throw any non-quota error so it surfaces in the error boundary
      // rather than being silently swallowed (unexpected errors should not be hidden).
      else {
        throw e;
      }
    }
  }, []);

  // Context menu: intercept right-click, store row + mouse position.
  const handleCellContextMenu = useCallback(
    (event: CellContextMenuEvent<EnrichedHoldingRow>) => {
      if (!event.data) return;
      const { h } = event.data;
      const ctx: HoldingRowContext = {
        kind: "holding",
        holdingId: h.holding_id,
        portfolioId: h.portfolio_id,
        instrumentId: h.instrument_id,
        entityId: h.entity_id,
        ticker: h.ticker,
        name: h.name,
      };
      const mouseEvent = event.event as MouseEvent | undefined;
      setCtxMenu({ row: ctx, x: mouseEvent?.clientX ?? 0, y: mouseEvent?.clientY ?? 0 });
    },
    [],
  );

  // ── Empty state guards ────────────────────────────────────────────────────

  if (holdings.length === 0) {
    return (
      <InlineEmptyState message="No holdings yet. Connect a brokerage or use Add Position to start tracking your book." />
    );
  }

  const allZeroQty = holdings.every((h) => Number(h.quantity) === 0);
  if (allZeroQty) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-4 px-4 text-center">
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
    // WHY fallback chain: getHoldings() never populates asset_class (it's absent
    // from the raw API response transform). We derive it here:
    //   1. Use h.asset_class if the field ever gets populated upstream.
    //   2. If sector is "ETF" (set by the EODHD ETF fallback), classify as "etf".
    //   3. Default to "equity" — the most common instrument type in a portfolio.
    const assetClass = h.asset_class ?? (sector === "ETF" ? "etf" : "equity");

    totalPnl += pnl;
    totalPnlCost += h.average_cost * h.quantity;

    return { h, livePrice, freshness, value, pnl, pnlPct, weight, sector, assetClass, dayChange, dayChangePct, dayChangeValue };
  });

  const totalPnlPct = totalPnlCost > 0 ? (totalPnl / totalPnlCost) * 100 : 0;

  // ── Pinned bottom row (AG Grid totals) ──────────────────────────────────────
  // WHY pinnedBottomRowData instead of a sibling <div>: AG Grid renders pinned
  // rows inside the grid DOM so they stay in sync with column widths, pinning,
  // and horizontal scroll automatically. A sibling <div> with hardcoded pixel
  // widths misaligns as soon as the user resizes a column or the TICKER pinned-
  // left column separates from the scrollable viewport. See BP-455.
  //
  // WHY synthetic `h` object: EnrichedHoldingRow requires an `h: Holding` field
  // (the cell renderers access it). The totals row doesn't correspond to a real
  // Holding, so we supply a zero-value placeholder. The TickerCellRenderer
  // checks `node.rowPinned === 'bottom'` and renders "TOTAL" instead of
  // `h.ticker`, so the placeholder values are never surfaced to the user.
  const pinnedBottomRow: EnrichedHoldingRow = {
    h: {
      holding_id: "__totals__",
      portfolio_id: "",
      instrument_id: "",
      entity_id: "",
      ticker: "",
      name: "",
      quantity: 0,
      average_cost: 0,
    },
    livePrice: 0,
    freshness: undefined,
    value: totalValue,
    pnl: totalPnl,
    pnlPct: totalPnlPct,
    weight: 0,
    sector: null,
    assetClass: "",
    dayChange: null,
    dayChangePct: null,
    dayChangeValue: null,
  };

  return (
    <div className="flex flex-col overflow-auto relative">
      {/* ── AG Grid table ─────────────────────────────────────────────────── */}
      {/* WHY pinnedBottomRowData: renders totals as a proper AG Grid pinned row,
          which tracks column widths/pinning/scroll automatically. Replaces the
          former hardcoded-pixel-width <div> footer (BP-455). */}
      <AgGridBase<EnrichedHoldingRow>
        rowData={enrichedRows}
        columnDefs={holdingsAgColumns}
        // WHY context: SparklineCellRenderer reads holdingsSeries from params.context.
        // Passing via AG Grid context avoids threading data through each ColDef.
        context={holdingsSeries ? { holdingsSeries } : undefined}
        getRowId={(p) => p.data.h.holding_id}
        onGridReady={handleGridReady}
        onRowClicked={(row) =>
          // PRD-0089 F2 step 11 (§6.6): ticker-first URL. Holding.ticker is
          // populated for every row (S1 portfolio service resolves on add).
          // encodeURIComponent passes dot-form tickers (BRK.B) through cleanly.
          // Falls back to UUID for the rare case where ticker is empty.
          router.push(
            `/instruments/${encodeURIComponent(row.h.ticker ?? row.h.instrument_id ?? row.h.entity_id)}`,
          )
        }
        onSortChanged={handleSortChanged}
        onColumnStateChanged={handleColumnStateChanged}
        onCellContextMenu={handleCellContextMenu}
        preventDefaultOnContextMenu={true}
        pinnedBottomRowData={[pinnedBottomRow]}
        // WHY rowHeight=20 (was 28): W2 density lock — fits more positions above the
        // fold. 20px gives one row per ~11px font line + 4.5px top + 4.5px bottom
        // padding, which is legible at text-[11px] while reducing wasted whitespace.
        rowHeight={20}
        className="flex-1"
      />

      {/* ── Floating context menu ─────────────────────────────────────────── */}
      {/* WHY floating (not ActionContextMenu wrapper): AG Grid renders its own
          row DOM — React component wrappers cannot be applied per-row. The
          floating div replicates ActionContextMenu's look using the same
          useContextMenuActions hook. Click-outside closes via document listener. */}
      {ctxMenu && ctxGroups.length > 0 && (
        <div
          className="fixed z-50 min-w-[160px] overflow-hidden rounded-[2px] border border-border bg-card py-1 "
          style={{ top: ctxMenu.y, left: ctxMenu.x }}
          // Stop propagation so the document click listener doesn't immediately close the menu.
          onClick={(e) => e.stopPropagation()}
        >
          {ctxGroups.map((group, i) => (
            <div key={group.category}>
              {i > 0 && <div className="my-1 h-px bg-border" />}
              <div className="px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {group.category}
              </div>
              {group.actions.map((action) => {
                const enabled = action.enabled ? action.enabled(actionCtx) : true;
                return (
                  <button
                    key={action.id}
                    disabled={!enabled}
                    className={cn(
                      "flex w-full cursor-default items-center gap-2 rounded-none px-3 py-1 text-[11px] text-foreground",
                      enabled
                        ? "hover:bg-muted/50"
                        : "opacity-40 cursor-not-allowed",
                    )}
                    onClick={() => {
                      void action.run(actionCtx);
                      setCtxMenu(null);
                    }}
                  >
                    <span className="flex-1 text-left">{action.label}</span>
                    {action.mnemonic && (
                      <span className="text-[9px] text-muted-foreground">
                        {action.mnemonic.toUpperCase()}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
