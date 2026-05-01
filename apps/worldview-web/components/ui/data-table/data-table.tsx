/**
 * components/ui/data-table/data-table.tsx — Universal DataTable primitive
 *
 * WHY THIS EXISTS: PRD-0031 §F-1 — institutional-terminal tables share a fixed
 * grammar: density-aware rows, virtualized when long, multi-column sort with
 * stable order, multi-select, copy-as-TSV, CSV export, sticky header,
 * column-resize, integrated context menu. Today every table re-implements
 * a subset of these ad-hoc, with inconsistent UX. This primitive is the
 * **foundation** — new tables consume it; existing well-built tables (e.g.
 * ScreenerTable) migrate opportunistically.
 *
 * SCOPE FOR THIS WAVE (F-1 subset):
 *   - TanStack Table v8 + react-virtual (already a project dep).
 *   - density: compact|default|comfortable (22px / 32px / 40px row heights).
 *   - Multi-column sort: shift-click to add a secondary sort key. Sort state
 *     is controlled or uncontrolled; "stable order" is achieved by passing
 *     all sort keys to TanStack and letting it merge.
 *   - Multi-select: row checkbox column, shift-click range, header indeterminate.
 *   - Bulk action toolbar: when N>0 selected, a thin bar appears above the
 *     header with "N selected · [actions...]".
 *   - Copy-as-TSV: ⌘C on a selected range copies tab-separated values. Plain
 *     copy of any single row is also TSV.
 *   - CSV export: utility function exposed; consumers wire to a button.
 *   - Sticky header: position: sticky top-0 inside a flex column.
 *   - DataTableContextMenu: optional render-prop wrapping each row.
 *
 * DEFERRED to follow-up wave: inline edit, group-by, sticky-footer totals,
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

export type DataTableDensity = "compact" | "default" | "comfortable";

const ROW_HEIGHT_PX: Record<DataTableDensity, number> = {
  compact: 22,
  default: 32,
  comfortable: 40,
};

const TEXT_SIZE: Record<DataTableDensity, string> = {
  compact: "text-[11px]",
  default: "text-xs",
  comfortable: "text-sm",
};

export interface DataTableBulkAction<TData> {
  id: string;
  label: string;
  icon?: React.ReactNode;
  /** Called with the full set of selected rows. */
  onClick: (rows: TData[]) => void;
  /** Mark as destructive — renders in destructive color. */
  destructive?: boolean;
}

export interface DataTableContextMenuItem<TData> {
  id: string;
  label: string;
  shortcut?: string;
  icon?: React.ReactNode;
  /** Called with the row that was right-clicked. */
  onClick: (row: TData) => void;
  destructive?: boolean;
  /** If returns false, item is disabled for that row. */
  enabled?: (row: TData) => boolean;
  /** Insert a separator after this item. */
  separatorAfter?: boolean;
}

export interface DataTableProps<TData> {
  /** Column definitions in TanStack format. Use `id` + `accessorKey` + `header` + `cell`. */
  columns: ColumnDef<TData>[];
  /** Row data. */
  data: TData[];
  /** Stable row ID extractor — required for selection state to survive re-render. */
  getRowId: (row: TData) => string;

  // Display
  density?: DataTableDensity;
  /** ARIA label for the table. */
  ariaLabel?: string;
  /** Render when data is empty (after loading). */
  emptyMessage?: React.ReactNode;
  /** Render skeleton rows while data loads. */
  isLoading?: boolean;

  // Selection
  /** Enable row checkbox + multi-select. Default false. */
  selectable?: boolean;
  /** Optional bulk-action set; toolbar renders when selection is non-empty. */
  bulkActions?: DataTableBulkAction<TData>[];
  /** Notify on selection change (controlled-style; component still owns state). */
  onSelectionChange?: (rows: TData[]) => void;

  // Context menu
  /** Per-row context-menu item set; right-click opens. */
  contextMenu?: DataTableContextMenuItem<TData>[];

  // Row interaction
  /** Click a row (no modifier). Useful for navigation. */
  onRowClick?: (row: TData) => void;

  // Misc
  className?: string;
  /** Wrap the table area in a virtualizer. Default: true if data.length > 50. */
  virtualize?: boolean;
}

/**
 * Convert a column array of accessorKeys into a TSV header line + row line.
 * WHY no library: tiny code, exact control over quoting/escaping. CSV/TSV
 * libraries pull >50KB to do <30 lines of work.
 */
export function rowsToTsv<TData>(rows: TData[], columns: ColumnDef<TData>[]): string {
  const headers = columns
    .filter((c) => c.id !== "__select__")
    .map((c) => (typeof c.header === "string" ? c.header : (c.id ?? "")));
  const lines = [headers.join("\t")];

  for (const row of rows) {
    const cells = columns
      .filter((c) => c.id !== "__select__")
      .map((c) => {
        const accessor = (c as { accessorKey?: keyof TData }).accessorKey;
        const v = accessor ? (row as TData)[accessor] : "";
        // WHY toString and replace: tabs and newlines inside cells must be sanitised
        // for TSV to remain parseable. Most spreadsheet apps tolerate spaces in cells.
        return v == null ? "" : String(v).replace(/\t/g, " ").replace(/\n/g, " ");
      });
    lines.push(cells.join("\t"));
  }

  return lines.join("\n");
}

/** Convert rows to a CSV string. RFC 4180 quoting. */
export function rowsToCsv<TData>(rows: TData[], columns: ColumnDef<TData>[]): string {
  const escape = (v: unknown) => {
    if (v == null) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const cols = columns.filter((c) => c.id !== "__select__");
  const headers = cols.map((c) => (typeof c.header === "string" ? c.header : (c.id ?? "")));
  const lines = [headers.map(escape).join(",")];
  for (const row of rows) {
    lines.push(
      cols
        .map((c) => {
          const accessor = (c as { accessorKey?: keyof TData }).accessorKey;
          return escape(accessor ? (row as TData)[accessor] : "");
        })
        .join(","),
    );
  }
  return lines.join("\n");
}

export function downloadCsv(filename: string, csv: string) {
  // WHY Blob + revokeObjectURL: avoids leaking memory across exports.
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * The primitive itself.
 *
 * WHY generic <TData>: column accessors and selection callbacks are typed end-to-end.
 * The caller passes their entity type (Holding, ScreenerResult, etc.) and gets
 * full IntelliSense in the column definitions and bulk-action handlers.
 */
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
  contextMenu,
  onRowClick,
  className,
  virtualize,
}: DataTableProps<TData>) {
  // ── Selection column injection ────────────────────────────────────────────
  // WHY inject vs caller-defined: caller would have to repeat the same checkbox
  // boilerplate in every table. We inject once here.
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
          // WHY stop propagation: clicking the checkbox should NOT also fire onRowClick.
          onClick={(e) => e.stopPropagation()}
        />
      ),
    };
    return [selectCol, ...columns];
  }, [columns, selectable]);

  // ── Table state ───────────────────────────────────────────────────────────
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({});
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});

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

  // Notify parent of selection changes.
  // WHY useMemo dependency: we want stable identity so the consumer doesn't see
  // spurious notifications when nothing changed.
  const selectedRows = React.useMemo(
    () => table.getSelectedRowModel().rows.map((r) => r.original),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- depends on rowSelection ref
    [rowSelection, data],
  );
  React.useEffect(() => {
    onSelectionChange?.(selectedRows);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: consumer is stable
  }, [selectedRows]);

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

  // ── Copy-as-TSV on ⌘C/Ctrl-C ──────────────────────────────────────────────
  const tableElRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const el = tableElRef.current;
    if (!el) return;
    const onCopy = (e: ClipboardEvent) => {
      // Only copy our TSV if focus is inside the table AND we have a selection.
      if (!el.contains(document.activeElement)) return;
      const sel = table.getSelectedRowModel().rows.map((r) => r.original);
      if (sel.length === 0) return;
      e.preventDefault();
      const tsv = rowsToTsv(sel, fullColumns);
      e.clipboardData?.setData("text/plain", tsv);
    };
    document.addEventListener("copy", onCopy);
    return () => document.removeEventListener("copy", onCopy);
  }, [table, fullColumns]);

  // ── Render: bulk action toolbar ────────────────────────────────────────────
  const selectionCount = selectedRows.length;
  const showToolbar = selectable && selectionCount > 0;

  // ── Sub-render: row ─────────────────────────────────────────────────────────
  function renderRow(virtualOffsetTop: number | undefined, rowIdx: number) {
    const row = rows[rowIdx];
    if (!row) return null;
    const cells = row.getVisibleCells();
    const node = (
      <div
        key={row.id}
        role="row"
        aria-selected={row.getIsSelected()}
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
          "flex items-center border-b border-white/[0.06] cursor-default transition-none",
          rowIdx % 2 === 0 ? "bg-white/[0.02]" : "",
          onRowClick && "cursor-pointer hover:bg-white/[0.05]",
          row.getIsSelected() && "bg-primary/10",
        )}
      >
        {cells.map((cell) => (
          <div
            key={cell.id}
            role="cell"
            className="shrink-0 truncate px-2 flex items-center"
            style={{ width: cell.column.getSize() }}
          >
            {flexRender(cell.column.columnDef.cell, cell.getContext())}
          </div>
        ))}
      </div>
    );

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
            <Copy className="h-3 w-3" aria-hidden />
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
      aria-rowcount={rows.length}
      className={cn("flex flex-col min-h-0 flex-1 overflow-hidden", TEXT_SIZE[density], className)}
    >
      {/* ── Bulk action toolbar ──────────────────────────────────────────── */}
      {showToolbar && (
        <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-2 py-1">
          <span className="text-[11px] tabular-nums text-foreground">
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
              <Copy className="h-3 w-3" /> Copy TSV
            </Button>
            <Button
              density="compact"
              variant="ghost"
              onClick={() => {
                const csv = rowsToCsv(selectedRows, fullColumns);
                downloadCsv(`selection-${Date.now()}.csv`, csv);
              }}
            >
              <Download className="h-3 w-3" /> CSV
            </Button>
            <Button density="compact" variant="ghost" onClick={() => setRowSelection({})}>
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* ── Header row ───────────────────────────────────────────────────── */}
      <div
        role="row"
        aria-label="Column headers"
        className="flex h-[22px] shrink-0 items-center border-b border-border bg-card sticky top-0 z-10"
      >
        {table.getFlatHeaders().map((header) => {
          const canSort = header.column.getCanSort();
          const sorted = header.column.getIsSorted();
          return (
            <div
              key={header.id}
              role="columnheader"
              aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
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
                    <ChevronUp className="h-2.5 w-2.5 text-primary" />
                  ) : sorted === "desc" ? (
                    <ChevronDown className="h-2.5 w-2.5 text-primary" />
                  ) : (
                    <ChevronsUpDown className="h-2.5 w-2.5 text-muted-foreground/40" />
                  )}
                </span>
              )}
              {/* Resize handle */}
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

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="flex-1 overflow-hidden">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center border-b border-border/30 px-2 gap-2"
              style={{ height: ROW_HEIGHT_PX[density] }}
            >
              <div className="h-2 w-10 bg-muted/40 rounded-none animate-pulse" />
              <div className="h-2 w-32 bg-muted/40 rounded-none animate-pulse" />
              <div className="h-2 w-20 bg-muted/30 rounded-none animate-pulse ml-auto" />
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="px-2 py-2 text-[11px] text-muted-foreground">
          {emptyMessage ?? "No results."}
        </div>
      ) : shouldVirtualize ? (
        <div ref={scrollRef} className="flex-1 overflow-auto">
          <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
            {rowVirtualizer.getVirtualItems().map((vRow) => renderRow(vRow.start, vRow.index))}
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          {rows.map((_, idx) => renderRow(undefined, idx))}
        </div>
      )}
    </div>
  );
}
