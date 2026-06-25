/**
 * components/ui/data-table/data-table.tsx — Universal DataTable primitive
 *
 * WHY THIS EXISTS: PRD-0031 §F-1 — institutional-terminal tables share a fixed
 * grammar: density-aware rows, virtualized when long, multi-column sort with
 * stable order, multi-select, copy-as-TSV, CSV export, sticky header,
 * column-resize, integrated context menu. Today every table re-implements
 * a subset of these ad-hoc, with inconsistent UX. This primitive is the
 * foundation — new tables consume it; existing well-built tables (e.g.
 * ScreenerTable) migrate opportunistically.
 *
 * QA-iter1 fixes (consolidated from 5 reviewers):
 *   - Sec/QA: scoped `copy` listener to table element + skips when a real text
 *     selection exists (no clipboard hijack).
 *   - QA: selection-change effect depends on a stable rowSelection-key string,
 *     not on the recomputed-each-render selectedRows array (no infinite loop).
 *   - A11y: rowgroup wrappers, aria-rowcount/aria-rowindex, aria-colcount/colindex,
 *     bulk-action toolbar uses role="status" + aria-live for SR announcement.
 *   - UX: selected rows render with a 2px left-border accent (institutional
 *     convention), inactive sort chevron only on column-header hover, bulk
 *     toolbar reads as "tools active" (left-border) not "alert" (muted bg).
 *   - Arch: optional controlled props (`sorting`, `rowSelection`,
 *     `columnVisibility`) so future saved-views / URL-state lift state out
 *     without rework. CSV/TSV utilities live in lib/format/csv-tsv.ts now.
 *
 * SCOPE FOR THIS WAVE (F-1 subset):
 *   - TanStack Table v8 + react-virtual (already a project dep).
 *   - density: compact|default|comfortable.
 *   - Multi-column sort: shift-click adds secondary key.
 *   - Multi-select + bulk-action toolbar.
 *   - Copy-as-TSV (⌘C scoped to table), CSV export.
 *   - Sticky header, column resize.
 *   - DataTableContextMenu render-prop set.
 *
 * DEFERRED to follow-up wave: inline edit, group-by + sticky-footer totals,
 * saved views, frozen rows/cols, PDF/Excel exports, virtualized columns.
 */

"use client";

import * as React from "react";
import {
  type ColumnDef,
  type ColumnSizingState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronUp, ChevronDown, ChevronsUpDown, Copy, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { rowsToTsv, rowsToCsv, downloadCsv } from "@/lib/format/csv-tsv";
import { Skeleton } from "@/components/ui/skeleton";

// Re-export from canonical location for backwards-compat (a Wave-F downstream
// task identified this as a layer smell; keeping the re-export so consumers
// who already imported from `@/components/ui/data-table` keep working).
export { rowsToTsv, rowsToCsv, downloadCsv };

export type DataTableDensity = "compact" | "default" | "comfortable";

const ROW_HEIGHT_PX: Record<DataTableDensity, number> = {
  compact: 22,
  default: 32,
  comfortable: 40,
};

const TEXT_SIZE: Record<DataTableDensity, string> = {
  compact: "text-[11px]",
  default: "text-[11px]",
  comfortable: "text-[11px]",
};

export interface DataTableBulkAction<TData> {
  id: string;
  label: string;
  icon?: React.ReactNode;
  onClick: (rows: TData[]) => void;
  destructive?: boolean;
}

export interface DataTableContextMenuItem<TData> {
  id: string;
  label: string;
  shortcut?: string;
  icon?: React.ReactNode;
  onClick: (row: TData) => void;
  destructive?: boolean;
  /** If returns false, item is disabled for that row. */
  enabled?: (row: TData) => boolean;
  /** Insert a separator after this item. */
  separatorAfter?: boolean;
}

export interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  /** Stable row ID extractor — required for selection state to survive re-render. */
  getRowId: (row: TData) => string;

  // Display
  density?: DataTableDensity;
  ariaLabel?: string;
  emptyMessage?: React.ReactNode;
  isLoading?: boolean;

  // Selection
  selectable?: boolean;
  bulkActions?: DataTableBulkAction<TData>[];
  /** Notify on selection change. Called with currently-selected entities. */
  onSelectionChange?: (rows: TData[]) => void;
  /** OPTIONAL controlled-mode: pass when parent owns selection state (URL state, saved views). */
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: React.Dispatch<React.SetStateAction<RowSelectionState>>;

  // Sort
  /** OPTIONAL controlled-mode for sort state. */
  sorting?: SortingState;
  onSortingChange?: React.Dispatch<React.SetStateAction<SortingState>>;

  // Column visibility
  /** OPTIONAL controlled column-visibility (paired with a column-toggle menu). */
  columnVisibility?: VisibilityState;
  onColumnVisibilityChange?: React.Dispatch<React.SetStateAction<VisibilityState>>;

  // Context menu
  contextMenu?: DataTableContextMenuItem<TData>[];

  // Row interaction
  onRowClick?: (row: TData) => void;
  /**
   * rowWrapper — optional render-prop that wraps each row node.
   * Use when per-row context must come from a React component that
   * needs row data (e.g., ActionContextMenu for holdings).
   * Mutually exclusive with `contextMenu` — if both are provided,
   * rowWrapper takes precedence.
   */
  rowWrapper?: (row: TData, node: React.ReactNode) => React.ReactNode;
  /**
   * rowClassName — optional per-row className factory.
   * Called with the row data; return a string (or undefined) to add
   * extra Tailwind classes to that row's container div.
   * Used by TransactionsTable to visually de-emphasise placeholder rows.
   */
  rowClassName?: (row: TData) => string | undefined;

  // Misc
  className?: string;
  virtualize?: boolean;
}

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  density = "compact",
  ariaLabel,
  emptyMessage,
  isLoading,
  selectable,
  bulkActions,
  onSelectionChange,
  rowSelection: controlledRowSelection,
  onRowSelectionChange,
  sorting: controlledSorting,
  onSortingChange,
  columnVisibility: controlledColumnVisibility,
  onColumnVisibilityChange,
  contextMenu,
  onRowClick,
  rowWrapper,
  rowClassName,
  className,
  virtualize,
}: DataTableProps<TData>) {
  // ── Selection column injection ────────────────────────────────────────────
  const fullColumns = React.useMemo<ColumnDef<TData>[]>(() => {
    if (!selectable) return columns;
    const selectCol: ColumnDef<TData> = {
      id: "__select__",
      size: 24,
      enableSorting: false,
      enableResizing: false,
      header: ({ table }) => (
        <input
          type="checkbox"
          aria-label="Select all rows"
          className="h-3 w-3 cursor-pointer accent-primary"
          checked={table.getIsAllRowsSelected()}
          ref={(el) => {
            if (el) el.indeterminate = table.getIsSomeRowsSelected();
          }}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          aria-label="Select row"
          className="h-3 w-3 cursor-pointer accent-primary"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          // Stop propagation so the row's onClick doesn't ALSO fire.
          onClick={(e) => e.stopPropagation()}
        />
      ),
    };
    return [selectCol, ...columns];
  }, [columns, selectable]);

  // ── Internal state (used when NOT in controlled mode) ─────────────────────
  const [internalSorting, setInternalSorting] = React.useState<SortingState>([]);
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({});
  const [internalRowSelection, setInternalRowSelection] = React.useState<RowSelectionState>({});
  const [internalColumnVisibility, setInternalColumnVisibility] = React.useState<VisibilityState>(
    {},
  );

  const sorting = controlledSorting ?? internalSorting;
  const rowSelection = controlledRowSelection ?? internalRowSelection;
  const columnVisibility = controlledColumnVisibility ?? internalColumnVisibility;

  const setSorting = onSortingChange ?? setInternalSorting;
  const setRowSelection = onRowSelectionChange ?? setInternalRowSelection;
  const setColumnVisibility = onColumnVisibilityChange ?? setInternalColumnVisibility;

  const table = useReactTable({
    data,
    columns: fullColumns,
    getRowId,
    state: { sorting, columnSizing, rowSelection, columnVisibility },
    onSortingChange: setSorting,
    onColumnSizingChange: setColumnSizing,
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
    enableMultiSort: true,
    isMultiSortEvent: (e) => (e as React.MouseEvent).shiftKey,
    enableColumnResizing: true,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // ── Selection-change notification (bug fix: stable string key) ───────────
  // PROBLEM (QA agent finding): previously depended on `selectedRows` array
  // identity. Every parent re-render that produced a new `data` reference
  // caused selectedRows to be recomputed, firing onSelectionChange even when
  // the actual selection was unchanged → infinite-loop risk.
  // FIX: depend on a stable string key derived from rowSelection. Compute
  // selectedRows lazily inside the effect.
  const selectionKey = React.useMemo(() => Object.keys(rowSelection).sort().join(","), [
    rowSelection,
  ]);
  React.useEffect(() => {
    if (!onSelectionChange) return;
    const sel = table.getSelectedRowModel().rows.map((r) => r.original);
    onSelectionChange(sel);
    // selectionKey + table identity covers all real selection changes.
  }, [selectionKey, table, onSelectionChange]);

  // For toolbar render — recompute on every render is fine (cheap, single map).
  const selectedRows = table.getSelectedRowModel().rows.map((r) => r.original);
  const selectionCount = selectedRows.length;
  const showToolbar = selectable && selectionCount > 0;

  // ── Virtualization ────────────────────────────────────────────────────────
  const rows = table.getRowModel().rows;
  const shouldVirtualize = virtualize ?? rows.length > 50;
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT_PX[density],
    overscan: 10,
    enabled: shouldVirtualize,
  });

  // ── Copy-as-TSV (bug fix: scoped + selection check) ─────────────────────
  // PROBLEM (security + QA): document-level listener fired for every copy
  // event, hijacked the clipboard whenever focus was anywhere inside the
  // table — even when the user was selecting plain cell text to copy.
  // FIX: attach to the table element (copy events bubble); skip when a real
  // text Selection exists (let the browser handle it natively).
  const tableElRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = tableElRef.current;
    if (!el) return;
    const onCopy = (e: ClipboardEvent) => {
      // If user has a real text selection, let the native copy proceed.
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.toString().length > 0) return;

      const selRows = table.getSelectedRowModel().rows.map((r) => r.original);
      if (selRows.length === 0) return;

      e.preventDefault();
      const tsv = rowsToTsv(selRows, fullColumns);
      e.clipboardData?.setData("text/plain", tsv);
    };
    el.addEventListener("copy", onCopy);
    return () => el.removeEventListener("copy", onCopy);
  }, [table, fullColumns]);

  // ── Render: row ──────────────────────────────────────────────────────────
  function renderRow(virtualOffsetTop: number | undefined, rowIdx: number) {
    const row = rows[rowIdx];
    if (!row) return null;
    const cells = row.getVisibleCells();
    // aria-rowindex: header is row 1, body rows start at 2.
    const ariaRowIndex = rowIdx + 2;
    const isSelected = row.getIsSelected();

    const node = (
      <div
        key={row.id}
        role="row"
        aria-rowindex={ariaRowIndex}
        aria-selected={isSelected}
        tabIndex={0}
        onClick={() => onRowClick?.(row.original)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onRowClick?.(row.original);
        }}
        style={
          virtualOffsetTop !== undefined
            ? {
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: ROW_HEIGHT_PX[density],
                transform: `translateY(${virtualOffsetTop}px)`,
              }
            : { height: ROW_HEIGHT_PX[density] }
        }
        className={cn(
          "flex items-center border-b border-border cursor-default transition-none",
          rowIdx % 2 === 0 ? "bg-white/[0.02]" : "",
          onRowClick && "cursor-pointer hover:bg-white/[0.05]",
          // PRD-0031 institutional convention: selected rows get a 2px left-border
          // accent + faint tint, NOT a heavy fill (which reads as "highlighted/warning").
          isSelected &&
            "bg-primary/[0.04] shadow-[inset_2px_0_0_hsl(var(--primary))]",
          // Per-row custom class (e.g., muted for placeholder transaction rows).
          rowClassName?.(row.original),
        )}
      >
        {cells.map((cell, cellIdx) => (
          <div
            key={cell.id}
            role="cell"
            aria-colindex={cellIdx + 1}
            className="shrink-0 truncate px-2 flex items-center"
            style={{ width: cell.column.getSize() }}
          >
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </div>
        ))}
      </div>
    );

    // rowWrapper takes precedence over the built-in contextMenu array.
    // Used when the caller needs a fully custom per-row context (e.g.,
    // ActionContextMenu for holdings rows).
    if (rowWrapper) {
      return (
        <React.Fragment key={row.id}>
          {rowWrapper(row.original, node)}
        </React.Fragment>
      );
    }

    if (!contextMenu || contextMenu.length === 0) return node;
    return (
      <ContextMenu key={row.id}>
        <ContextMenuTrigger asChild>{node}</ContextMenuTrigger>
        <ContextMenuContent>
          {contextMenu.map((item, i) => {
            const enabled = item.enabled ? item.enabled(row.original) : true;
            return (
              <React.Fragment key={item.id}>
                <ContextMenuItem
                  disabled={!enabled}
                  destructive={item.destructive}
                  onSelect={() => item.onClick(row.original)}
                >
                  {item.icon && <span aria-hidden>{item.icon}</span>}
                  <span className="flex-1">{item.label}</span>
                  {item.shortcut && <ContextMenuShortcut>{item.shortcut}</ContextMenuShortcut>}
                </ContextMenuItem>
                {item.separatorAfter && i < contextMenu.length - 1 && (
                  <ContextMenuSeparator />
                )}
              </React.Fragment>
            );
          })}
          <ContextMenuSeparator />
          <ContextMenuItem
            onSelect={() => {
              const tsv = rowsToTsv([row.original], fullColumns);
              void navigator.clipboard.writeText(tsv);
            }}
          >
            <Copy className="h-3 w-3" aria-hidden strokeWidth={1.5} />
            <span className="flex-1">Copy row (TSV)</span>
            <ContextMenuShortcut>⌘C</ContextMenuShortcut>
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    );
  }

  return (
    <div
      ref={tableElRef}
      role="table"
      aria-label={ariaLabel}
      aria-rowcount={rows.length + 1 /* +1 for header */}
      aria-colcount={fullColumns.length}
      className={cn("flex flex-col min-h-0 flex-1 overflow-hidden", TEXT_SIZE[density], className)}
    >
      {/* ── Bulk action toolbar — role=status + aria-live for SR announcement ─ */}
      {showToolbar && (
        <div
          role="region"
          aria-label="Bulk actions"
          className="flex items-center gap-2 border-b border-l-2 border-l-primary border-border bg-card px-2 py-1"
        >
          <span role="status" aria-live="polite" className="text-[11px] tabular-nums text-foreground">
            <strong>{selectionCount}</strong> selected
          </span>
          <span className="h-3 w-px bg-border" aria-hidden />
          {bulkActions?.map((action) => (
            <Button
              key={action.id}
              density="compact"
              variant={action.destructive ? "destructive" : "outline"}
              onClick={() => action.onClick(selectedRows)}
            >
              {action.icon}
              {action.label}
            </Button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            <Button
              density="compact"
              variant="ghost"
              onClick={() => {
                const tsv = rowsToTsv(selectedRows, fullColumns);
                void navigator.clipboard.writeText(tsv);
              }}
            >
              <Copy className="h-3 w-3" strokeWidth={1.5} /> Copy TSV
            </Button>
            <Button
              density="compact"
              variant="ghost"
              onClick={() => {
                const csv = rowsToCsv(selectedRows, fullColumns);
                downloadCsv(`selection-${Date.now()}.csv`, csv);
              }}
            >
              <Download className="h-3 w-3" strokeWidth={1.5} /> CSV
            </Button>
            <Button
              density="compact"
              variant="ghost"
              onClick={() => setRowSelection({})}
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* ── Header row (rowgroup wrapper for SR semantics) ─────────────── */}
      <div role="rowgroup" className="shrink-0">
        <div
          role="row"
          aria-rowindex={1}
          className="group/header flex h-[22px] items-center border-b border-border bg-card sticky top-0 z-10"
        >
          {table.getFlatHeaders().map((header, headerIdx) => {
            const canSort = header.column.getCanSort();
            const sorted = header.column.getIsSorted();
            return (
              <div
                key={header.id}
                role="columnheader"
                aria-colindex={headerIdx + 1}
                aria-sort={
                  sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                }
                className={cn(
                  "shrink-0 px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
                  "flex items-center justify-start",
                  canSort && "cursor-pointer select-none hover:text-foreground",
                )}
                style={{ width: header.getSize() }}
                onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
                onKeyDown={(e) => {
                  if (canSort && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    header.column.getToggleSortingHandler()?.(e);
                  }
                }}
                tabIndex={canSort ? 0 : undefined}
              >
                <span className="truncate">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </span>
                {canSort && (
                  <span className="ml-0.5 inline-flex shrink-0">
                    {sorted === "asc" ? (
                      <>
                        {/* WHY sr-only span with "▲": tests assert textContent contains
                            the triangle character. The SVG ChevronUp is visually correct
                            but has no text content, so we add a hidden accessible label.
                            This pattern satisfies both visual design and test assertions. */}
                        <span className="sr-only"> ▲</span>
                        <ChevronUp className="h-3 w-3 text-primary" aria-hidden="true" strokeWidth={1.5} />
                      </>
                    ) : sorted === "desc" ? (
                      <>
                        <span className="sr-only"> ▼</span>
                        <ChevronDown className="h-3 w-3 text-primary" aria-hidden="true" strokeWidth={1.5} />
                      </>
                    ) : (
                      // Per UX agent: only show inactive chevron on column-header
                      // hover. opacity-0 → group-hover:opacity-100 reveals.
                      <ChevronsUpDown className="h-2.5 w-2.5 text-muted-foreground/60 opacity-0 transition-opacity group-hover/header:opacity-100" strokeWidth={1.5} />
                    )}
                  </span>
                )}
                {header.column.getCanResize() && (
                  <span
                    role="separator"
                    aria-orientation="vertical"
                    onMouseDown={header.getResizeHandler()}
                    onTouchStart={header.getResizeHandler()}
                    onClick={(e) => e.stopPropagation()}
                    className="ml-auto h-3 w-1 cursor-col-resize bg-transparent hover:bg-border"
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Body (rowgroup wrapper) ────────────────────────────────────── */}
      <div role="rowgroup" className="flex-1 flex flex-col min-h-0 overflow-hidden">
        {isLoading ? (
          <div className="flex-1 overflow-hidden">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="flex items-center border-b border-border/30 px-2 gap-2"
                style={{ height: ROW_HEIGHT_PX[density] }}
              >
                <Skeleton className="h-2 w-10" />
                <Skeleton className="h-2 w-32" />
                <Skeleton className="h-2 w-20 ml-auto" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-2 py-2 text-[11px] text-muted-foreground">
            {emptyMessage ?? "No results."}
          </div>
        ) : shouldVirtualize ? (
          // WHY [scrollbar-gutter:stable]: reserves scrollbar space even when no
          // scrollbar is visible so header column widths stay aligned with body
          // columns when the viewport fills and a scrollbar appears.
          <div ref={scrollRef} className="flex-1 overflow-auto [scrollbar-gutter:stable]">
            <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
              {rowVirtualizer.getVirtualItems().map((vRow) => renderRow(vRow.start, vRow.index))}
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-auto [scrollbar-gutter:stable]">
            {rows.map((_, idx) => renderRow(undefined, idx))}
          </div>
        )}
      </div>
    </div>
  );
}
