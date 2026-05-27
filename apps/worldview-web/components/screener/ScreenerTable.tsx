/**
 * components/screener/ScreenerTable.tsx — AG-Grid screener table wrapper
 * (PRD-0089 Wave I-A · Block A · T-IA-03)
 *
 * WHY THIS EXISTS:
 *   The screener page used to inline the AG-Grid block AND the row-hover
 *   toolbar management (~60 LOC of refs, callbacks, rAF dance) inside
 *   `page.tsx`. Extracting them into a single `<ScreenerTable>` lets:
 *     1. The Workspace screener panel mount the same table with a different
 *        row-click target (e.g. open a side panel instead of a route push).
 *     2. The row-hover toolbar logic (CellMouseOver / Out + rAF debounce) be
 *        owned by ONE component instead of getting copy-pasted at every
 *        consumer.
 *     3. `page.tsx` shed ~60 LOC and read top-to-bottom as orchestration only.
 *
 * KEY DECISIONS:
 *   - **20px rows**: the screener is the one platform surface that uses 20px
 *     rows (per Terminal-Dark spec). The architecture test
 *     `screener-row-height.test.ts` forbids `rowHeight: 22` anywhere in
 *     `components/screener/`.
 *   - **`<div data-table-grid>` wrapper**: an architecture test
 *     (`data-table-grid-scope.test.ts`) verifies every dense AG-Grid lives
 *     inside such a wrapper so global CSS overrides apply.
 *   - **AgGridBase.headerHeight is hardcoded to 28**: passing
 *     `headerHeight={22}` would be a no-op. We don't bother — the plan
 *     §5.1 mentions 22 but AgGridBase ignores it. Documented as a deviation.
 *
 * ROW-HOVER TOOLBAR PATTERN (preserved from page.tsx):
 *   - AG-Grid React does NOT expose row-level mouse events; we listen at
 *     the cell level and deduplicate by `rowIndex`.
 *   - When the cursor crosses a column boundary, `CellMouseOut` fires
 *     BETWEEN cells in the same row, which would flicker the toolbar.
 *     We resolve this with a `requestAnimationFrame` debounce: the next
 *     `CellMouseOver` cancels the pending clear by flipping a ref flag.
 *
 * WHO USES IT:
 *   - `app/(app)/screener/page.tsx`.
 *   - Future: Workspace screener panel.
 *
 * DESIGN REF: docs/designs/0089/08-screener.md §4.1 Row 4 + §6.1
 * PLAN REF:   docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-03
 */

"use client";
// WHY "use client": AG-Grid is browser-only; we also manage refs + state.

import { useCallback, useRef, useState } from "react";
import type {
  ColDef,
  ColGroupDef,
  GridReadyEvent,
  CellMouseOverEvent,
} from "ag-grid-community";
import { AgGridBase } from "@/components/ui/ag-grid/AgGridBase";
import { RowHoverToolbar } from "@/components/screener/RowHoverToolbar";
import type { ScreenerResult } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ScreenerTableProps {
  /** Result rows (already client-side filtered + accumulated). */
  rows: ScreenerResult[];
  /** AG-Grid column definitions, including any sparkline cell renderer. */
  columnDefs: (ColDef<ScreenerResult> | ColGroupDef<ScreenerResult>)[];
  /** Fires when a row is clicked. Use to route to /instruments/{ticker}. */
  onRowClick: (row: ScreenerResult) => void;
  /** Bubbled out so the parent can store the GridApi ref (column state etc.). */
  onGridReady: (event: GridReadyEvent<ScreenerResult>) => void;
  /** Optional — fires when the user clicks the "+" compare action on a hovered row. */
  onCompare?: (ticker: string) => void;
  /** Optional — watchlist add handler for the hover toolbar. */
  onWatch?: (instrumentId: string) => void;
  /** Optional — alert dialog handler for the hover toolbar. */
  onAlert?: (instrumentId: string) => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ScreenerTable({
  rows,
  columnDefs,
  onRowClick,
  onGridReady,
  onCompare,
  onWatch,
  onAlert,
}: ScreenerTableProps) {
  // ── Row-hover state ────────────────────────────────────────────────────
  // WHY (data + rect) tuple: RowHoverToolbar needs both the row's data
  // (for the ticker / instrument_id) and the row's bounding rect (for the
  // absolute positioning). Storing one without the other would force two
  // setStates per hover, doubling the re-render count.
  const [hoveredRow, setHoveredRow] = useState<{ data: ScreenerResult; rect: DOMRect } | null>(null);

  // WHY a row-index ref: AG-Grid fires CellMouseOver for EVERY cell entry.
  // Deduplicating by rowIndex saves us from a setState per cell traversal
  // (12 columns × every hover ≈ 12 wasted renders without this guard).
  const lastHoveredRowIndex = useRef<number | null>(null);

  // WHY a "pending clear" flag: when the cursor crosses a column boundary,
  // CellMouseOut fires before the next CellMouseOver. Without the rAF
  // debounce + ref flag, the toolbar flickers off then back on every time
  // the user moves their cursor sideways through the row.
  const mouseOutPendingRef = useRef(false);

  const handleCellMouseOver = useCallback((e: CellMouseOverEvent<ScreenerResult>) => {
    mouseOutPendingRef.current = false;
    if (e.rowIndex === lastHoveredRowIndex.current) return;
    lastHoveredRowIndex.current = e.rowIndex;
    if (!e.data || !e.event) return;
    // `.ag-row` is the AG-Grid row DOM element; we need its rect (NOT the
    // cell's rect) so the floating toolbar lines up with the full row.
    const rowEl = (e.event.target as HTMLElement).closest(".ag-row");
    if (!rowEl) return;
    setHoveredRow({ data: e.data, rect: rowEl.getBoundingClientRect() });
  }, []);

  const handleCellMouseOut = useCallback(() => {
    mouseOutPendingRef.current = true;
    requestAnimationFrame(() => {
      // If a fresh CellMouseOver fired before the rAF tick, it flipped the
      // flag back to false — bail. Otherwise the cursor genuinely left the
      // table area, so clear the hovered row.
      if (!mouseOutPendingRef.current) return;
      lastHoveredRowIndex.current = null;
      setHoveredRow(null);
    });
  }, []);

  return (
    // WHY data-table-grid: the architecture test
    // `data-table-grid-scope.test.ts` requires every dense AG-Grid in the
    // app to live under this attribute so the global Terminal-Dark CSS
    // overrides (font, row separator, hover colour) target the right tree.
    <div data-table-grid className="relative flex-1 min-h-0 flex flex-col overflow-hidden">
      <AgGridBase<ScreenerResult>
        rowData={rows}
        columnDefs={columnDefs}
        // 20px rows = the screener's signature density (240 cells above the
        // fold at 1440×900 with 12 default columns). The arch test forbids
        // any other value inside `components/screener/`.
        rowHeight={20}
        getRowId={(p) => p.data.instrument_id}
        onGridReady={onGridReady}
        onRowClicked={onRowClick}
        onCellMouseOver={handleCellMouseOver}
        onCellMouseOut={handleCellMouseOut}
        className="flex-1"
      />

      {/* ── Row-hover floating toolbar ─────────────────────────────── */}
      {/* WHY rendered as a sibling to AgGridBase (not inside): the toolbar
       *  uses `position: absolute` against the wrapper, so it lives in the
       *  same stacking context. AG-Grid's internal DOM is virtualised; we
       *  must not inject children into its row elements. */}
      {hoveredRow && (
        <RowHoverToolbar
          rowRect={hoveredRow.rect}
          ticker={hoveredRow.data.ticker ?? ""}
          instrumentId={hoveredRow.data.instrument_id}
          // WHY noop fallbacks (not optional props on RowHoverToolbar):
          // RowHoverToolbar treats the three handlers as required. We supply
          // empty fns when the parent omits them so the toolbar still renders
          // (greyed buttons still expose tooltips even when actions no-op).
          onWatch={(id) => onWatch?.(id)}
          onAlert={(id) => onAlert?.(id)}
          onCompare={(ticker) => onCompare?.(ticker)}
        />
      )}
    </div>
  );
}
