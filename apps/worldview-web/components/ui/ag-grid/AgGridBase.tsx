"use client";
// WHY "use client": AgGridReact is a browser-only component (needs DOM + ResizeObserver).

import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-alpine.css";
import "./ag-grid-theme.css";

import { AgGridReact } from "ag-grid-react";
import type {
  ColDef,
  ColGroupDef,
  GridReadyEvent,
  GetRowIdParams,
  RowClickedEvent,
  CellMouseOverEvent,
  CellMouseOutEvent,
  CellContextMenuEvent,
  SortChangedEvent,
} from "ag-grid-community";

export interface AgGridBaseProps<TData extends object> {
  rowData: TData[];
  columnDefs: (ColDef<TData> | ColGroupDef<TData>)[];
  onRowClicked?: (row: TData) => void;
  getRowId?: (params: GetRowIdParams<TData>) => string;
  onGridReady?: (params: GridReadyEvent<TData>) => void;
  /** Extra Tailwind classes applied to the wrapper div (e.g. height overrides). */
  className?: string;
  /** Fires when a cell is right-clicked. Use with preventDefaultOnContextMenu to show a custom menu. */
  onCellContextMenu?: (event: CellContextMenuEvent<TData>) => void;
  /** Fires when the sort order changes. Use to sync sort state to URL or external state. */
  onSortChanged?: (event: SortChangedEvent<TData>) => void;
  /** Fires when column width, visibility, or order changes. Use to persist column state to localStorage. */
  onColumnStateChanged?: () => void;
  /** When true, suppresses the browser's native right-click context menu. */
  preventDefaultOnContextMenu?: boolean;
  /**
   * Fires when the pointer moves over a cell (once per cell, not per pixel).
   * Use this for row-hover affordances: the event carries `data` (row) and
   * `rowIndex` so the caller can compute the row's bounding rect via the
   * AG Grid API (e.g. `gridApi.getDisplayedRowAtIndex(rowIndex)?.setExpanded()`).
   *
   * WHY CellMouseOverEvent (not a custom RowMouseOver):
   *   AG Grid v35 does not expose onRowMouseOver/onRowMouseOut at the grid
   *   option level. CellMouseOverEvent fires on every cell entry and reliably
   *   carries both `data` and the native MouseEvent for bounding rect needs.
   */
  onCellMouseOver?: (event: CellMouseOverEvent<TData>) => void;
  /** Fires when the pointer leaves a cell. Use to hide row-hover overlays. */
  onCellMouseOut?: (event: CellMouseOutEvent<TData>) => void;
  /**
   * WHY pinnedBottomRowData: AG Grid renders pinned rows inside the grid DOM,
   * keeping them in sync with column widths, pinning, and horizontal scroll
   * automatically. Use this instead of a sibling <div> footer for totals rows.
   * See BP-455 — sibling <div> footers misalign when columns are resized or
   * the TICKER column is pinned left.
   */
  pinnedBottomRowData?: TData[];
}

/**
 * AgGridBase — terminal-themed AG Grid wrapper.
 *
 * WHY THIS EXISTS: all AG Grid instances in the app share the same terminal
 * aesthetic (28px rows, monospace font, design-token colour vars, ALL-CAPS
 * headers, no border-radius). Centralising that in one component means the
 * screener, portfolio holdings table, and financial statements table all look
 * identical without copy-pasting class strings or CSS imports.
 *
 * WHY ag-theme-alpine-dark + CSS var overrides (not a custom theme): the new
 * AG Grid v32+ theming API generates inline styles that fight with our
 * Tailwind/CSS-var system. The CSS-var override approach works with the stable
 * legacy theme API (still shipped in v35 Community) and gives us full control
 * with one CSS file.
 *
 * WHY rowHeight=28, headerHeight=28: Bloomberg terminal row height is ~24–28px.
 * 28px gives one row per ~11px font line + comfortable padding without wasting
 * vertical space the way Alpine's default 42px does.
 */
export function AgGridBase<TData extends object>({
  rowData,
  columnDefs,
  onRowClicked,
  getRowId,
  onGridReady,
  className,
  onCellContextMenu,
  onSortChanged,
  onColumnStateChanged,
  preventDefaultOnContextMenu,
  pinnedBottomRowData,
  onCellMouseOver,
  onCellMouseOut,
}: AgGridBaseProps<TData>) {
  const colStateHandler = onColumnStateChanged;

  return (
    <div
      className={`terminal-ag-grid ag-theme-alpine-dark w-full h-full${className ? ` ${className}` : ""}`}
    >
      <AgGridReact<TData>
        // WHY theme="legacy": AG Grid v33+ defaults to the new Theming API which
        // generates inline styles and ignores CSS class themes (ag-theme-alpine-dark).
        // The wrapper class above + ag-grid-theme.css depend on legacy CSS theming.
        // Without this prop the grid renders white-on-white. P0-2 (PLAN-0088).
        theme="legacy"
        rowData={rowData}
        columnDefs={columnDefs}
        pinnedBottomRowData={pinnedBottomRowData}
        rowHeight={28}
        headerHeight={28}
        groupHeaderHeight={22}
        getRowId={getRowId}
        onGridReady={onGridReady}
        onRowClicked={
          onRowClicked
            ? (e: RowClickedEvent<TData>) => {
                if (e.data) onRowClicked(e.data);
              }
            : undefined
        }
        onCellContextMenu={onCellContextMenu}
        onSortChanged={onSortChanged}
        onCellMouseOver={onCellMouseOver}
        onCellMouseOut={onCellMouseOut}
        onColumnResized={colStateHandler ? () => colStateHandler() : undefined}
        onColumnVisible={colStateHandler ? () => colStateHandler() : undefined}
        onColumnMoved={colStateHandler ? () => colStateHandler() : undefined}
        preventDefaultOnContextMenu={preventDefaultOnContextMenu}
        enableCellTextSelection={true}
        defaultColDef={{
          sortable: true,
          resizable: true,
          minWidth: 40,
        }}
      />
    </div>
  );
}
