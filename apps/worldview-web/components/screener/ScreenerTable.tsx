/**
 * components/screener/ScreenerTable.tsx — virtualized screener table (customizable columns)
 *
 * WHY THIS EXISTS: The screener must display up to hundreds of instruments in a
 * single scrollable table. Rendering all rows in the DOM at once causes frame
 * drops and sluggish scrolling — unacceptable for institutional traders who
 * expect Bloomberg-level responsiveness. @tanstack/react-virtual renders only
 * the visible rows (+ overscan buffer), keeping the DOM small regardless of
 * result count.
 *
 * WHY USER-CUSTOMIZABLE COLUMNS (PLAN-0051 T-B-2-06): different analysts care
 * about different fields. The table now takes the column list as a prop —
 * the screener page loads it from localStorage via `lib/screener-columns`,
 * and the ⚙ ColumnSettingsPopover lets users hide/reorder columns. Only
 * `visible: true` columns render here, and they render in the order given.
 *
 * WHY tabular-nums + font-mono on ALL numbers: Column alignment is critical for
 * scanning. "9.43" must line up with "12.70" — proportional fonts break this.
 *
 * WHY THE INLINE SPARKLINE COLUMN (PLAN-0051 T-B-2-09): the sparklines prop
 * carries pre-fetched 30-day OHLCV bars per instrument id. We render via
 * MiniChart (pure SVG, see that file) — fast even for many rows.
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 * DATA SOURCE: POST /v1/fundamentals/screen (via runScreener gateway method)
 *              + POST /v1/quotes/bars/batch (via getBatchOhlcvBars / sparklines hook)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, PLAN-0051 Wave B
 */

"use client";
// WHY "use client": uses useVirtualizer (browser DOM measurements) + useRef + useRouter

import { useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { HeatCell } from "./HeatCell";
import { MiniChart } from "./MiniChart";
import { cn } from "@/lib/utils";
import type { ScreenerResult, OHLCVBar } from "@/types/api";
import { DEFAULT_COLUMNS, type ScreenerColumn } from "@/lib/screener-columns";

// ── Types ─────────────────────────────────────────────────────────────────────

/** SortDir — cycle: none → asc → desc → none */
export type SortDir = "asc" | "desc" | null;

export interface SortState {
  key: SortableKey | null;
  dir: SortDir;
}

/**
 * SortableKey — the user-facing column keys that map to a ScreenerResult field.
 *
 * WHY a string-literal type (not keyof ScreenerResult): the table column keys
 * ("price", "change", "marketCap") differ from the API field names
 * ("current_price", "daily_return", "market_cap"). The mapping happens in the
 * cell renderer below; this type lists only the SORTABLE column keys.
 */
export type SortableKey =
  | "ticker" | "name" | "sector"
  | "price" | "change" | "marketCap" | "pe"
  | "revenue" | "beta" | "score";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** formatCap — abbreviated market cap / revenue (e.g. 2.3T, 450B, 8.5M) */
function formatCap(val: number | null | undefined): string {
  if (val == null) return "—";
  if (val >= 1e12) return `${(val / 1e12).toFixed(1)}T`;
  if (val >= 1e9)  return `${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6)  return `${(val / 1e6).toFixed(1)}M`;
  return val.toFixed(0);
}

/**
 * COLUMN_PIXEL_WIDTHS — fixed pixel widths per column key.
 *
 * WHY pixel-fixed (not flex): financial tables need horizontal alignment that
 * doesn't shift when filtering changes the data. Pixel-fixed columns keep
 * "9.43" sitting in the same x-position as "12.70" across all rows.
 *
 * WHY external map (not on ScreenerColumn): width is a presentation concern
 * tightly coupled to this table — keeping it here lets us tune widths without
 * forcing every consumer of ScreenerColumn to re-specify them.
 */
const COLUMN_PIXEL_WIDTHS: Record<string, string> = {
  ticker: "70px",
  name: "160px",
  sector: "100px",
  price: "80px",
  change: "70px",
  marketCap: "80px",
  pe: "60px",
  revenue: "80px",
  beta: "55px",
  score: "70px",
  range52w: "100px",
  volume: "80px",
  sparkline: "70px",
};

// ── Cell renderer ────────────────────────────────────────────────────────────

/**
 * renderCell — switches on the column key to render the right cell content.
 *
 * WHY a switch (not a per-column render fn on ScreenerColumn): keeping ALL
 * cell logic in one place makes it trivial to spot a missing case at a glance
 * and to add a new formatter without touching three other modules.
 */
function renderCell(
  col: ScreenerColumn,
  row: ScreenerResult,
  sparkline: OHLCVBar[] | undefined,
): React.ReactNode {
  switch (col.key) {
    case "ticker":
      return (
        // WHY text-primary: ticker is actionable (row click navigates to instrument).
        <span className="font-mono text-[11px] tabular-nums text-primary truncate">
          {row.ticker}
        </span>
      );

    case "name":
      return <span className="text-[11px] text-foreground truncate">{row.name}</span>;

    case "sector":
      return (
        <span className="text-[11px] text-muted-foreground truncate">
          {row.gics_sector ?? "—"}
        </span>
      );

    case "price": {
      const v = row.current_price;
      return (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {v != null ? `$${v.toFixed(2)}` : "—"}
        </span>
      );
    }

    case "change": {
      if (row.daily_return == null) {
        return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
      }
      const pct = row.daily_return * 100;
      const isPos = pct > 0;
      const isNeg = pct < 0;
      return (
        // WHY pill: directional change pills are an institutional convention
        // (tastytrade, TradingView). The bg-tint communicates direction in
        // peripheral vision before the user reads the digits.
        <span className={cn(
          "inline-flex items-center justify-center font-mono text-[10px] tabular-nums px-1 rounded-[2px]",
          isPos && "bg-positive/10 text-positive",
          isNeg && "bg-negative/10 text-negative",
          !isPos && !isNeg && "text-muted-foreground",
        )}>
          {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
        </span>
      );
    }

    case "marketCap":
      return (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {formatCap(row.market_cap)}
        </span>
      );

    case "pe":
      return (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {row.pe_ratio != null ? row.pe_ratio.toFixed(1) : "—"}
        </span>
      );

    case "revenue":
      return (
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {row.revenue != null ? formatCap(row.revenue) : "—"}
        </span>
      );

    case "beta": {
      if (row.beta == null) {
        return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
      }
      // WHY color-coded beta: > 1.5 = high risk (warning); < 0.5 = defensive (muted).
      const isHigh = row.beta > 1.5;
      const isLow = row.beta < 0.5;
      return (
        <span className={cn(
          "font-mono text-[11px] tabular-nums",
          isHigh ? "text-warning" : isLow ? "text-muted-foreground" : "text-foreground",
        )}>
          {row.beta.toFixed(2)}
        </span>
      );
    }

    case "score":
      return <HeatCell score={row.market_impact_score} />;

    case "range52w":
      return (
        // WHY placeholder bar: backend pending; signals "coming soon" without
        // breaking the column layout.
        <div className="h-1 bg-border rounded-none overflow-hidden w-full" title="Backend pending">
          <div className="h-full bg-muted-foreground/20 w-0" />
        </div>
      );

    case "volume":
      return (
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground" title="Backend pending">—</span>
      );

    case "sparkline":
      return (
        <MiniChart
          bars={sparkline}
          ariaLabel={`${row.ticker} 30-day price trend`}
        />
      );

    default:
      // WHY render dash for unknown keys: defensive fallback if a column is
      // added to DEFAULT_COLUMNS but not yet wired here. Avoids blank cells.
      return <span className="font-mono text-[11px] text-muted-foreground">—</span>;
  }
}

// ── SortIcon ─────────────────────────────────────────────────────────────────

function SortIcon({ sortKey, sort }: { sortKey?: SortableKey; sort: SortState }) {
  if (!sortKey) return null;
  if (sort.key !== sortKey) {
    return <ChevronsUpDown className="h-2.5 w-2.5 ml-0.5 text-muted-foreground/40 shrink-0" aria-hidden />;
  }
  return sort.dir === "asc"
    ? <ChevronUp className="h-2.5 w-2.5 ml-0.5 text-primary shrink-0" aria-hidden />
    : <ChevronDown className="h-2.5 w-2.5 ml-0.5 text-primary shrink-0" aria-hidden />;
}

// ── ScreenerTable ──────────────────────────────────────────────────────────────

interface ScreenerTableProps {
  rows: ScreenerResult[];
  isLoading: boolean;
  sort: SortState;
  onSort: (key: SortableKey) => void;
  /**
   * Ordered column list — only entries with visible:true are rendered.
   * WHY optional with a sane default: legacy callers (e.g. /instruments page)
   * can keep using ScreenerTable without opting into column customization.
   * The screener page passes the user's localStorage prefs explicitly.
   */
  columns?: ScreenerColumn[];
  /** Per-instrument 30d bars for the sparkline column. Defaults to {}. */
  sparklines?: Record<string, OHLCVBar[]>;
}

/**
 * ScreenerTable — the core virtualized data table.
 *
 * WHY useMemo on visibleColumns: every parent re-render would otherwise create
 * a new filtered array, defeating any downstream memoisation in the row map.
 */
export function ScreenerTable({
  rows,
  isLoading,
  sort,
  onSort,
  columns,
  sparklines = {},
}: ScreenerTableProps) {
  const router = useRouter();
  const scrollRef = useRef<HTMLDivElement>(null);

  // WHY default to DEFAULT_COLUMNS sans sparkline:
  //   - Legacy callers (instruments page) don't fetch sparkline data, so
  //     showing the column would render empty placeholders. Hiding it for
  //     the default case keeps the legacy view tidy.
  const visibleColumns = useMemo(
    () => {
      const list = columns ?? DEFAULT_COLUMNS.filter((c) => c.key !== "sparkline").map((c) => ({ ...c }));
      return list.filter((c) => c.visible);
    },
    [columns],
  );

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    // WHY estimateSize 22: PRD-0031 §0.2 mandates 22px row height.
    estimateSize: () => 22,
    // WHY overscan 10: prevents flashing empty rows during fast scroll.
    overscan: 10,
  });

  return (
    <div className="flex flex-col min-h-0 flex-1 overflow-hidden">
      {/* ── Sticky column headers ────────────────────────────────────────── */}
      <div
        className="flex items-center h-[22px] border-b border-border bg-card shrink-0"
        role="row"
        aria-label="Column headers"
      >
        {visibleColumns.map((col) => {
          const width = COLUMN_PIXEL_WIDTHS[col.key] ?? "80px";
          // WHY "score"|"sparkline" not in SortableKey: the sortable union
          // intentionally excludes sparkline; score IS sortable.
          const sortKey: SortableKey | undefined = col.sortable
            ? (col.key as SortableKey)
            : undefined;
          return (
            <div
              key={col.key}
              role="columnheader"
              aria-sort={
                sort.key === sortKey
                  ? sort.dir === "asc"
                    ? "ascending"
                    : "descending"
                  : "none"
              }
              className={cn(
                "shrink-0 px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
                col.align === "right" ? "text-right" : "text-left",
                sortKey ? "cursor-pointer select-none hover:text-foreground" : "",
                "flex items-center",
                col.align === "right" ? "justify-end" : "justify-start",
              )}
              style={{ width, minWidth: width }}
              onClick={() => sortKey && onSort(sortKey)}
              onKeyDown={(e) => {
                if (sortKey && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onSort(sortKey);
                }
              }}
              tabIndex={sortKey ? 0 : undefined}
              aria-label={sortKey ? `Sort by ${col.label}` : col.label}
            >
              <span className="truncate">{col.label.toUpperCase()}</span>
              <SortIcon sortKey={sortKey} sort={sort} />
            </div>
          );
        })}
      </div>

      {/* ── Virtualized rows ─────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="flex-1 overflow-hidden">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="h-[22px] flex items-center border-b border-border/30 px-2 gap-2">
              <div className="h-2 w-10 bg-muted/40 rounded-none animate-pulse" style={{ animationDelay: `${i * 20}ms` }} />
              <div className="h-2 w-32 bg-muted/40 rounded-none animate-pulse" style={{ animationDelay: `${i * 20 + 10}ms` }} />
              <div className="h-2 w-20 bg-muted/30 rounded-none animate-pulse ml-auto" style={{ animationDelay: `${i * 20 + 5}ms` }} />
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="px-2 py-1 text-[11px] text-muted-foreground">
          No results. Adjust filters and apply.
        </div>
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto">
          <div
            style={{
              height: rowVirtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {rowVirtualizer.getVirtualItems().map((vRow) => {
              const row = rows[vRow.index];
              const sparkline = sparklines[row.instrument_id];
              return (
                <div
                  key={vRow.key}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: 22,
                    transform: `translateY(${vRow.start}px)`,
                  }}
                  className={cn(
                    "flex items-center border-b border-white/[0.06] cursor-pointer transition-none",
                    vRow.index % 2 === 0 ? "bg-white/[0.02] hover:bg-white/[0.05]" : "hover:bg-white/[0.04]",
                  )}
                  onClick={() => router.push(`/instruments/${row.entity_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") router.push(`/instruments/${row.entity_id}`);
                  }}
                  role="row"
                  tabIndex={0}
                  aria-label={`Navigate to ${row.ticker} instrument page`}
                >
                  {visibleColumns.map((col) => {
                    const width = COLUMN_PIXEL_WIDTHS[col.key] ?? "80px";
                    return (
                      <div
                        key={col.key}
                        role="cell"
                        className={cn(
                          "shrink-0 px-2 overflow-hidden",
                          col.align === "right" ? "flex justify-end" : "flex justify-start",
                        )}
                        style={{ width, minWidth: width }}
                      >
                        {renderCell(col, row, sparkline)}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
