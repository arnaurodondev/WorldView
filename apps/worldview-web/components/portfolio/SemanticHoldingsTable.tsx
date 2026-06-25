/**
 * components/portfolio/SemanticHoldingsTable.tsx — 12-column holdings table
 *
 * WHY THIS EXISTS: The portfolio holdings table is the most data-critical surface
 * for a portfolio manager. Twelve columns give enough data to make re-balancing
 * decisions without navigating to the instrument detail page.
 *   Ticker | Name | Qty | Avg Cost | Current | Day$ | Day% | P&L$ | P&L% | Value | Weight | Sector
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
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9
 * DESIGN REFERENCE: PLAN-0044 Wave 2, PLAN-0059 F-1, PLAN-0071 Phase 6
 */

"use client";

import { useState, useEffect, useMemo, useCallback, useRef, lazy, Suspense } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
// R3 polish (DS §15.12): shared EmptyState primitive replaces InlineEmptyState
// for the no-holdings state — icon + centred layout match every other surface.
import { EmptyState } from "@/components/primitives/EmptyState";
// Wallet = "your book" category icon for the no-holdings empty state.
import { Wallet } from "lucide-react";
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

// ── Lazy-loaded dialogs ───────────────────────────────────────────────────────
// WHY lazy: ClosePositionDialog is only opened from the AG Grid context menu,
// never on initial page load. React.lazy keeps it out of the initial bundle so
// the portfolio page cold-start time is not penalised. The fallback={null}
// means no visible flicker — the dialog appears as soon as the chunk loads
// (typically <100ms on cached assets).
const ClosePositionDialog = lazy(() =>
  import("./ClosePositionDialog").then((m) => ({ default: m.ClosePositionDialog }))
);

// ── Constants ─────────────────────────────────────────────────────────────────

const HOLDINGS_COLS_KEY = "worldview-holdings-cols";

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
  /**
   * Sector label → instrument_ids lookup, sourced from the SAME
   * /sector-breakdown endpoint that powers the SECTOR EXPOSURE panel
   * (sectorIdMapFromSegments). Optional, additive fallback for the SECTOR
   * column (DESIGN-QA P-2 fix).
   *
   * WHY THIS EXISTS: the `sectors` prop above is keyed off the instrument
   * *fundamentals* overview (holdingOverviews[id].sector), which is null for
   * every holding in the current deployment — so the SECTOR column rendered
   * "—" on every row even though the SECTOR EXPOSURE panel (fed by the
   * breakdown segments) clearly knew each holding's sector. This prop lets the
   * table reuse the breakdown source: we invert it to instrument_id → sector
   * and use it whenever the fundamentals `sectors` entry is missing. When the
   * prop is absent the column degrades to its previous behaviour (no
   * regression for callers that don't pass it).
   */
  sectorIdMap?: Record<string, string[]>;
  /** Total portfolio market value — used to compute Weight column */
  totalValue: number;
  /**
   * 14-day close-price series — drives the SPARK column (PLAN-0108 W4-T401).
   *
   * KEYING (corrected in the R1 sprint): the map is keyed by INSTRUMENT_ID —
   * that is the key the S9 GET /v1/market/sparklines response uses and what
   * useHoldingsSeries passes through. SparklineCellRenderer looks up by
   * instrument_id first with a ticker fallback for legacy callers. (The
   * previous doc claimed ticker keying, which is why the column rendered "—"
   * for every row.)
   *
   * WHY optional: the series loads asynchronously after the holdings table
   * renders. When undefined or empty, SparklineCellRenderer renders "—"
   * placeholders instead of crashing. This matches the lazy-load pattern used
   * by the `sectors` prop.
   */
  series?: Record<string, number[]>;
  /**
   * Asset-class lookup keyed by instrument_id — drives the ASSET column badge
   * (R1 sprint, completes the W4-T401 "T-4-03" TODO). Derived by
   * usePortfolioData from the transactions response (S1 enriches transactions
   * with asset_class via an instruments JOIN). Missing entries render the
   * AssetTypeCellRenderer "—" placeholder.
   */
  assetClasses?: Record<string, string | null>;

  // ── PRD-0114 W5 Close Position wiring ────────────────────────────────────
  /**
   * portfolioId — S1 portfolio UUID passed to ClosePositionDialog so it can
   * POST to the correct portfolio. Undefined for the root (aggregate) portfolio
   * which is read-only (no add/close allowed on root).
   */
  portfolioId?: string;
  /**
   * portfolioKind — "manual" | "brokerage" | "root". Controls whether
   * the "Close Position" context menu item is shown. Root portfolios are
   * read-only; the Close Position option is hidden there.
   */
  portfolioKind?: "manual" | "brokerage" | "root";
  /** Auth token forwarded to ClosePositionDialog for the S9 POST call. */
  accessToken?: string | null;
  /** Called after a successful Close Position so the parent can refetch holdings. */
  onHoldingsRefetch?: () => void;
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
  sectorIdMap,
  totalValue,
  series,
  assetClasses,
  portfolioId,
  portfolioKind,
  accessToken,
  onHoldingsRefetch,
}: SemanticHoldingsTableProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // ── AG Grid API ref ───────────────────────────────────────────────────────
  const gridApiRef = useRef<GridApi<EnrichedHoldingRow> | null>(null);

  // ── Context menu state ────────────────────────────────────────────────────
  const [ctxMenu, setCtxMenu] = useState<CtxMenuState | null>(null);
  // PRD-0114 W5-T06: Close Position dialog state.
  // WHY useState (not URL param): the dialog is transient — it should not persist
  // across page refreshes. Storing the target holding in state keeps the dialog
  // lifecycle tied to the current component mount.
  const [closePositionHolding, setClosePositionHolding] = useState<Holding | null>(null);

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

  // ── Sector fallback map (DESIGN-QA P-2) ───────────────────────────────────
  // Invert sectorIdMap (sector → instrument_ids[]) into instrument_id → sector
  // so the row enrichment below can look a holding's sector up in O(1). This
  // is the SAME data the SECTOR EXPOSURE panel uses, so the column and the
  // panel can no longer disagree. Memoised on sectorIdMap identity — it only
  // changes when the /sector-breakdown query refetches.
  const sectorByInstrumentFromBreakdown = useMemo(() => {
    const map: Record<string, string> = {};
    if (!sectorIdMap) return map;
    for (const [sector, ids] of Object.entries(sectorIdMap)) {
      for (const id of ids) map[id] = sector;
    }
    return map;
  }, [sectorIdMap]);

  // ── Enrich rows (R4: memoised) ────────────────────────────────────────────
  // R4 hardening: this block ran inline in the render body, producing a FRESH
  // enrichedRows array (and pinned-row object) on every render — including
  // renders where neither holdings nor quotes changed (e.g. the page-level
  // sector-filter chip toggling, context-menu open/close, parent hover
  // state). AG Grid diffs rowData by reference first; a fresh array forces
  // its change-detection pass each time. Memoising on the four real inputs
  // restores identity stability: toggling the sector filter OFF hands AG
  // Grid the exact same array it had before (holdings is reference-stable on
  // the unfiltered path — filterHoldingsBySector returns the same ref).
  // WHY above the early returns: rules-of-hooks — the hook must run on every
  // render, including the empty/zero-qty renders that return early below.
  const { enrichedRows, pinnedBottomRow } = useMemo(() => {
    let totalPnl = 0;
    let totalPnlCost = 0;
    // R1 sprint: totals for the pinned bottom row. dayChangeSeen
    // distinguishes "no quote has a change yet" (render "—") from a genuine
    // $0.00 flat day.
    let totalDayChange = 0;
    let dayChangeSeen = false;
    // Sum of per-row weights — by construction this is 100% whenever
    // totalValue equals the sum of row values, but we sum the actual
    // rendered weights so the TOTAL row never contradicts the column above
    // it (e.g. when the KPI totalValue used a slightly different live-price
    // fallback for one row).
    let totalWeight = 0;

    const rows: EnrichedHoldingRow[] = holdings.map((h) => {
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
      // DESIGN-QA P-2: prefer the fundamentals sector, but fall back to the
      // /sector-breakdown source (the one the SECTOR EXPOSURE panel uses) when
      // fundamentals is null — which it currently is for every holding. null
      // only when BOTH sources lack the instrument.
      const sector =
        sectors?.[h.instrument_id] ??
        sectorByInstrumentFromBreakdown[h.instrument_id] ??
        null;
      const dayChange = quote?.change ?? null;
      const dayChangePct = quote?.change_pct ?? null;
      const dayChangeValue = dayChange != null ? dayChange * h.quantity : null;

      totalPnl += pnl;
      totalPnlCost += h.average_cost * h.quantity;
      // R1 sprint: accumulate the TOTAL row's day change + weight.
      if (dayChangeValue != null) {
        totalDayChange += dayChangeValue;
        dayChangeSeen = true;
      }
      totalWeight += weight;

      // PLAN-0114 W6: DIV YLD column reads annualizedDividendYield. The S9
      // get_holdings fan-out now populates Holding.annualizedDividendYield from
      // S3 fundamentals (mapped in lib/api/portfolios.ts), so surface it directly
      // on the row; it falls back to null (column renders "—") when the backend
      // has no yield for the instrument.
      return { h, livePrice, freshness, value, pnl, pnlPct, weight, sector, dayChange, dayChangePct, dayChangeValue, annualizedDividendYield: h.annualizedDividendYield ?? null };
    });

    const totalPnlPct = totalPnlCost > 0 ? (totalPnl / totalPnlCost) * 100 : 0;

    // R1 sprint: portfolio-level day-change percentage for the TOTAL row.
    // Yesterday's close value = today's value − today's change; guard
    // against a zero/negative denominator (e.g. a brand-new position whose
    // entire value IS today's change) — null renders "—" instead of a
    // nonsense percentage.
    const totalDayBase = totalValue - totalDayChange;
    const totalDayChangePct =
      dayChangeSeen && totalDayBase > 0
        ? (totalDayChange / totalDayBase) * 100
        : null;

    // ── Pinned bottom row (AG Grid totals) ──────────────────────────────────
    // WHY pinnedBottomRowData instead of a sibling <div>: AG Grid renders
    // pinned rows inside the grid DOM so they stay in sync with column
    // widths, pinning, and horizontal scroll automatically. A sibling <div>
    // with hardcoded pixel widths misaligns as soon as the user resizes a
    // column or the TICKER pinned-left column separates from the scrollable
    // viewport. See BP-455.
    //
    // WHY synthetic `h` object: EnrichedHoldingRow requires an `h: Holding`
    // field (the cell renderers access it). The totals row doesn't correspond
    // to a real Holding, so we supply a zero-value placeholder. The
    // TickerCellRenderer checks `node.rowPinned === 'bottom'` and renders
    // "TOTAL" instead of `h.ticker`, so the placeholder values are never
    // surfaced to the user.
    const pinned: EnrichedHoldingRow = {
      h: {
        holding_id: "__totals__",
        portfolio_id: "",
        instrument_id: "",
        entity_id: "",
        ticker: "",
        // 2026-06-10 "—" cleanup: the TOTAL row's NAME cell renders this
        // string (NameCellRenderer pinned branch) — a real position count
        // instead of a dead dash in the widest cell of the totals line.
        name: `${holdings.length} position${holdings.length === 1 ? "" : "s"}`,
        quantity: 0,
        average_cost: 0,
      },
      livePrice: 0,
      freshness: undefined,
      value: totalValue,
      pnl: totalPnl,
      pnlPct: totalPnlPct,
      // R1 sprint: real totals instead of the previous "—" placeholders.
      // weight sums the per-row weights (≈100% by construction); day change
      // is the book-level day P&L; the pct is computed off yesterday's close
      // base.
      weight: totalWeight,
      sector: null,
      dayChange: null,
      dayChangePct: totalDayChangePct,
      dayChangeValue: dayChangeSeen ? totalDayChange : null,
      // TOTAL row has no single-position yield → null (DIV YLD renders "—").
      annualizedDividendYield: null,
    };

    return { enrichedRows: rows, pinnedBottomRow: pinned };
  }, [holdings, quotes, sectors, sectorByInstrumentFromBreakdown, totalValue]);

  // ── Empty state guards ────────────────────────────────────────────────────

  if (holdings.length === 0) {
    // R3 polish (DS §15.12): named "no holdings" state via the shared
    // EmptyState primitive. Copy lives in lib/copy/empty-states.ts
    // (portfolio.no-holdings-table) — title keeps the exact "No holdings
    // yet." string older tests pin, so this is a layout/registry migration
    // with zero copy drift.
    return (
      <EmptyState
        condition="empty-cold-start"
        copyKey="portfolio.no-holdings-table"
        icon={Wallet}
      />
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

  // (Row enrichment + pinned TOTAL row live in the useMemo above the empty-
  // state guards — R4 hardening moved them there for rowData identity
  // stability across unrelated re-renders. See that block's comments.)

  return (
    // WHY h-full: SemanticHoldingsTable is placed inside a `flex-1 min-h-0` div
    // in HoldingsTab. Without h-full here, this div collapses to 0px height because
    // it has no intrinsic content height — the AG Grid inside (which uses h-full
    // internally) cannot expand to fill a parent that itself has no height.
    // overflow-auto is removed here because the height must be explicit for the
    // AG Grid viewport's own overflow-y scroll to function correctly (the grid
    // manages its own scroll container; a wrapping overflow-auto on a 0px div
    // created the black void). min-h-0 is kept so the flex child can shrink below
    // its content size inside the outer flex column.
    // R4 hardening (a11y): role="region" + aria-label name the grid surface.
    // AgGridBase (shared component — not editable from this surface) exposes
    // no aria-label passthrough, and AG Grid's internal role="grid" element
    // is otherwise anonymous: a screen-reader rotor listed an unnamed grid
    // among the page's landmarks. The labelled region wrapper gives AT users
    // a navigable, named entry point to the holdings table.
    <div
      className="flex flex-col h-full relative"
      role="region"
      aria-label="Portfolio holdings table"
    >
      {/* ── AG Grid table ─────────────────────────────────────────────────── */}
      {/* WHY pinnedBottomRowData: renders totals as a proper AG Grid pinned row,
          which tracks column widths/pinning/scroll automatically. Replaces the
          former hardcoded-pixel-width <div> footer (BP-455). */}
      {/*
       * WHY context object: AG Grid's `context` prop is the canonical way to
       * pass arbitrary data into cell renderers without encoding it in ColDef
       * values (which AG Grid deep-clones on every render cycle). Both
       * SparklineCellRenderer and AssetTypeCellRenderer read from context:
       *
       *   - holdingsSeries: Record<ticker, number[]>  → SPARK column
       *   - assetClasses:   Record<instrument_id, string | null>  → ASSET column
       *
       * WHY `series ?? {}` default: the prop is optional (async load). The
       * renderers already guard against empty series with a "—" placeholder,
       * but passing undefined would cause a runtime TypeError in the null-check
       * inside SparklineCellRenderer's context cast.
       *
       * assetClasses (R1 sprint — closes the T-4-03 TODO): keyed by
       * instrument_id, derived from the transactions response in
       * usePortfolioData. Holdings without a matching key fall back to the
       * renderer's "—" placeholder (graceful degradation preserved).
       */}
      <AgGridBase<EnrichedHoldingRow>
        rowData={enrichedRows}
        columnDefs={holdingsAgColumns}
        // R2 sprint: 22px rows/header — the terminal density target every
        // other strip on this page already uses (h-[22px] strips, 22px
        // skeleton rows). AgGridBase defaults to 28; the optional overrides
        // landed this round (design-system agent).
        rowHeight={22}
        headerHeight={22}
        getRowId={(p) => p.data.h.holding_id}
        onGridReady={handleGridReady}
        onRowClicked={(row) =>
          router.push(`/instruments/${encodeURIComponent(row.h.instrument_id ?? row.h.entity_id)}`)
        }
        onSortChanged={handleSortChanged}
        onColumnStateChanged={handleColumnStateChanged}
        onCellContextMenu={handleCellContextMenu}
        preventDefaultOnContextMenu={true}
        pinnedBottomRowData={[pinnedBottomRow]}
        className="flex-1"
        context={{
          // Keyed by instrument_id (S9 sparklines response keying — R1 fix;
          // SparklineCellRenderer also accepts ticker keys as a fallback).
          holdingsSeries: series ?? {},
          // Keyed by instrument_id — matches AssetTypeCellRenderer's lookup
          // key. Empty map (no transactions yet) → renderer shows "—".
          assetClasses: assetClasses ?? {},
        }}
      />

      {/* ── Floating context menu ─────────────────────────────────────────── */}
      {/* WHY floating (not ActionContextMenu wrapper): AG Grid renders its own
          row DOM — React component wrappers cannot be applied per-row. The
          floating div replicates ActionContextMenu's look using the same
          useContextMenuActions hook. Click-outside closes via document listener. */}
      {ctxMenu && ctxGroups.length > 0 && (
        <div
          className="fixed z-50 min-w-[160px] overflow-hidden rounded-[2px] border border-border bg-card py-1 shadow-md"
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

          {/* PRD-0114 W5-T06: "Close Position" menu item.
              WHY separate group (not in ctxGroups): ClosePositionDialog is a W5
              addition; the existing command-actions system is not yet aware of it.
              Adding it here directly avoids touching the command-actions registry
              which could break other callers. The separator + "POSITION" label
              matches the Bloomberg-style grouping convention used by ctxGroups.
              WHY only for non-root + quantity > 0: root portfolios are read-only
              (S1 rejects); quantity=0 means the position is already closed. */}
          {portfolioKind !== "root" && portfolioId && (() => {
            // Look up the full Holding by holdingId so ClosePositionDialog has
            // quantity + ticker + instrument_id without storing extra data in ctxMenu.
            // WHY IIFE: allows a local variable inside JSX without a separate component.
            const holding = holdings.find(
              (h) => h.holding_id === ctxMenu.row.holdingId
            );
            if (!holding || holding.quantity <= 0) return null;
            return (
              <>
                <div className="my-1 h-px bg-border" />
                <div className="px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Position
                </div>
                <button
                  className="flex w-full cursor-default items-center gap-2 rounded-none px-3 py-1 text-[11px] text-negative hover:bg-negative/10"
                  onClick={() => {
                    setClosePositionHolding(holding);
                    setCtxMenu(null);
                  }}
                >
                  <span className="flex-1 text-left">Close Position</span>
                </button>
              </>
            );
          })()}
        </div>
      )}

      {/* PRD-0114 W5-T05/06: ClosePositionDialog — lazy-loaded, only mounts when
          the user selects "Close Position" from the context menu. Suspense fallback
          is null (no visible flicker) because the dialog doesn't need to show until
          the chunk loads. */}
      {closePositionHolding && portfolioId && (
        <Suspense fallback={null}>
          <ClosePositionDialog
            holding={closePositionHolding}
            portfolioId={portfolioId}
            accessToken={accessToken}
            onSuccess={() => {
              // Trigger parent refetch so the holdings table refreshes with the
              // updated quantities/values after the position is closed.
              onHoldingsRefetch?.();
            }}
            onClose={() => setClosePositionHolding(null)}
          />
        </Suspense>
      )}
    </div>
  );
}
