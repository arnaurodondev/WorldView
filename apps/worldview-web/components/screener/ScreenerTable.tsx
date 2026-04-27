/**
 * components/screener/ScreenerTable.tsx — 12-column virtualized screener table
 *
 * WHY THIS EXISTS: The screener must display up to hundreds of instruments in a
 * single scrollable table. Rendering all rows in the DOM at once causes frame
 * drops and sluggish scrolling — unacceptable for institutional traders who
 * expect Bloomberg-level responsiveness. @tanstack/react-virtual renders only
 * the visible rows (+ overscan buffer), keeping the DOM small regardless of
 * result count.
 *
 * WHY 12 COLUMNS: PRD-0031 §7.1 mandates 12 columns for screener density parity
 * with Bloomberg EQUITY SCREEN. More columns = more signal per viewport. Columns
 * without backend data show "—" to preserve the layout and signal future work.
 *
 * WHY tabular-nums + font-mono on ALL numbers: Column alignment is critical for
 * scanning. "9.43" must line up with "12.70" — proportional fonts break this.
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 * DATA SOURCE: POST /v1/fundamentals/screen (via runScreener gateway method)
 * DESIGN REFERENCE: PRD-0031 §7 Screener, Wave 3
 */

"use client";
// WHY "use client": uses useVirtualizer (browser DOM measurements) + useRef + useRouter

import { useRef } from "react";
import { useRouter } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { HeatCell } from "./HeatCell";
import { cn } from "@/lib/utils";
import type { ScreenerResult } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

/** SortDir — cycle: none → asc → desc → none */
export type SortDir = "asc" | "desc" | null;

export interface SortState {
  key: SortableKey | null;
  dir: SortDir;
}

/** Sortable columns — only fields present on ScreenerResult are sortable */
export type SortableKey = keyof Pick<
  ScreenerResult,
  "ticker" | "name" | "gics_sector" | "daily_return" | "market_cap" | "pe_ratio" | "market_impact_score"
  | "current_price" | "revenue" | "beta"
>;

// ── Column definitions ─────────────────────────────────────────────────────────

/**
 * ColDef — column definition for the screener table.
 *
 * WHY width as fixed pixel string: columns must not flex or shrink — financial
 * tables need absolute alignment so numbers stay in the same horizontal position
 * as the user scans rows. Using flex-1 would cause numbers to shift.
 *
 * WHY align separate from sortKey: header alignment must mirror data alignment
 * (right-aligned headers for right-aligned number columns). This is enforced
 * by pairing them in the column definition rather than setting them independently.
 */
interface ColDef {
  header: string;
  width: string;       // e.g. "70px" — fixed width applied to both header and cell
  align: "left" | "right" | "center";
  sortKey?: SortableKey;  // undefined = not sortable
  render: (row: ScreenerResult) => React.ReactNode;
}

/** formatCap — market cap abbreviated (e.g. 2.3T, 450B, 8.5M) */
function formatCap(val: number | null | undefined): string {
  if (val == null) return "—";
  if (val >= 1e12) return `${(val / 1e12).toFixed(1)}T`;
  if (val >= 1e9)  return `${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6)  return `${(val / 1e6).toFixed(1)}M`;
  return val.toFixed(0);
}

/**
 * COLS — 12 column definitions per PRD-0031 §7.1
 *
 * WHY some columns show "—" placeholder text: Revenue, Beta, Price, 52W Range,
 * and Volume are not returned by the current screener backend. Showing "—"
 * preserves the 12-column layout (consistent visual weight) and signals to users
 * that data is planned — not missing by design. The tooltip "Backend pending"
 * communicates the intent clearly.
 */
const COLS: ColDef[] = [
  {
    header: "TICKER",
    width: "70px",
    align: "left",
    sortKey: "ticker",
    render: (r) => (
      // WHY text-primary: ticker cells are actionable (clicking navigates to the
      // instrument page). Primary color signals interactivity without an underline.
      <span className="font-mono text-[11px] tabular-nums text-primary truncate">
        {r.ticker}
      </span>
    ),
  },
  {
    header: "NAME",
    width: "160px",
    align: "left",
    sortKey: "name",
    render: (r) => (
      <span className="text-[11px] text-foreground truncate">{r.name}</span>
    ),
  },
  {
    header: "SECTOR",
    width: "100px",
    align: "left",
    sortKey: "gics_sector",
    render: (r) => (
      <span className="text-[11px] text-muted-foreground truncate">{r.gics_sector ?? "—"}</span>
    ),
  },
  {
    header: "PRICE",
    width: "80px",
    align: "right",
    sortKey: "current_price",
    render: (r) => (
      // WHY $-prefix: institutional convention — prices always show currency symbol.
      // WHY 2dp: standard equity price precision (fractions below $1 may need more, but
      // large-caps always 2dp). Truncation to "—" only when truly unavailable.
      <span className="font-mono text-[11px] tabular-nums text-foreground">
        {r.current_price != null ? `$${r.current_price.toFixed(2)}` : "—"}
      </span>
    ),
  },
  {
    header: "CHG%",
    width: "70px",
    align: "right",
    sortKey: "daily_return",
    render: (r) => {
      if (r.daily_return == null) return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
      const pct = r.daily_return * 100;
      const isPos = pct > 0;
      const isNeg = pct < 0;
      return (
        // WHY pill (bg tint + colored text): directional change pills are an institutional
        // terminal pattern (tastytrade, TradingView, Refinitiv). The background tint makes
        // direction scannable in peripheral vision — traders don't need to read the sign
        // character; the color block fires before parsing the number.
        <span className={cn(
          "inline-flex items-center justify-center font-mono text-[10px] tabular-nums px-1 rounded-[2px]",
          isPos && "bg-positive/10 text-positive",
          isNeg && "bg-negative/10 text-negative",
          !isPos && !isNeg && "text-muted-foreground",
        )}>
          {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
        </span>
      );
    },
  },
  {
    header: "MKT CAP",
    width: "80px",
    align: "right",
    sortKey: "market_cap",
    render: (r) => (
      <span className="font-mono text-[11px] tabular-nums text-foreground">{formatCap(r.market_cap)}</span>
    ),
  },
  {
    header: "P/E",
    width: "60px",
    align: "right",
    sortKey: "pe_ratio",
    render: (r) => (
      <span className="font-mono text-[11px] tabular-nums text-foreground">
        {r.pe_ratio != null ? r.pe_ratio.toFixed(1) : "—"}
      </span>
    ),
  },
  {
    header: "REVENUE",
    width: "80px",
    align: "right",
    sortKey: "revenue",
    render: (r) => (
      // WHY abbreviated format: revenue in T/B/M matching market-cap abbreviation for
      // visual consistency. A stock screener user reads "394B" faster than "$394,000,000,000".
      <span className="font-mono text-[11px] tabular-nums text-foreground">
        {r.revenue != null ? formatCap(r.revenue) : "—"}
      </span>
    ),
  },
  {
    header: "BETA",
    width: "55px",
    align: "right",
    sortKey: "beta",
    render: (r) => {
      if (r.beta == null) return <span className="font-mono text-[11px] tabular-nums text-muted-foreground">—</span>;
      // WHY color-coded beta: beta > 1.5 = high risk (amber), < 0.5 = defensive (muted-foreground),
      // otherwise normal (foreground). Instant risk signal without reading the number.
      const isHigh = r.beta > 1.5;
      const isLow = r.beta < 0.5;
      return (
        <span className={cn(
          "font-mono text-[11px] tabular-nums",
          isHigh ? "text-warning" : isLow ? "text-muted-foreground" : "text-foreground",
        )}>
          {r.beta.toFixed(2)}
        </span>
      );
    },
  },
  {
    header: "SCORE",
    width: "70px",
    align: "right",
    sortKey: "market_impact_score",
    render: (r) => (
      // WHY HeatCell: market_impact_score is the S6 AI signal score (0–1).
      // HeatCell renders it as a color-coded 0–100 integer — the canonical
      // screener visualization per DESIGN_SYSTEM.md.
      <HeatCell score={r.market_impact_score} />
    ),
  },
  {
    header: "52W RANGE",
    width: "100px",
    align: "center",
    render: () => (
      // WHY placeholder bar: a flat gray bar communicates "range visualization
      // coming" without breaking the column layout. Title explains intent.
      <div className="h-1 bg-border rounded-none overflow-hidden w-full" title="Backend pending">
        <div className="h-full bg-muted-foreground/20 w-0" />
      </div>
    ),
  },
  {
    header: "VOLUME",
    width: "80px",
    align: "right",
    render: () => (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground" title="Backend pending">—</span>
    ),
  },
];

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
}

/**
 * ScreenerTable — the core virtualized data table.
 *
 * Uses @tanstack/react-virtual for row virtualization. With virtual scroll,
 * only ~25 rows are in the DOM at any time regardless of total result count —
 * keeping scroll performance smooth even with 500+ results.
 */
export function ScreenerTable({ rows, isLoading, sort, onSort }: ScreenerTableProps) {
  const router = useRouter();

  // WHY scrollRef on outer div: useVirtualizer measures the scrollable container
  // to determine which items are in the viewport. The ref must point to the element
  // that has overflow-auto/overflow-scroll.
  const scrollRef = useRef<HTMLDivElement>(null);

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    // WHY ref callback: getScrollElement() connects the virtualizer to the DOM
    // container so it can measure scrollTop and clientHeight.
    getScrollElement: () => scrollRef.current,
    // WHY estimateSize 22: PRD-0031 §0.2 mandates 22px row height throughout the
    // terminal. Exact estimate avoids layout recalculation on scroll.
    estimateSize: () => 22,
    // WHY overscan 10: renders 10 rows beyond the visible viewport in each direction.
    // This prevents flashing empty rows when the user scrolls quickly.
    overscan: 10,
  });

  return (
    // WHY flex-col: header row is shrink-0, scroll area is flex-1. Together they
    // fill the parent container exactly without overflow or underflow.
    <div className="flex flex-col min-h-0 flex-1 overflow-hidden">
      {/* ── Sticky column headers ────────────────────────────────────────── */}
      {/*
       * WHY sticky header inside a flex-col: the header stays at the top while
       * the virtualizer scroll div below scrolls independently. This is the
       * standard virtualized table pattern — do NOT put the header inside the
       * scroll container.
       */}
      <div
        className="flex items-center h-[22px] border-b border-border bg-card shrink-0"
        role="row"
        aria-label="Column headers"
      >
        {COLS.map((col) => (
          <div
            key={col.header}
            role="columnheader"
            aria-sort={
              sort.key === col.sortKey
                ? sort.dir === "asc"
                  ? "ascending"
                  : "descending"
                : "none"
            }
            className={cn(
              "shrink-0 px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
              col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left",
              // WHY cursor-pointer only when sortable: non-sortable columns
              // (backend-pending ones) should not suggest interactivity
              col.sortKey ? "cursor-pointer select-none hover:text-foreground" : "",
              "flex items-center",
              col.align === "right" ? "justify-end" : col.align === "center" ? "justify-center" : "justify-start",
            )}
            style={{ width: col.width, minWidth: col.width }}
            onClick={() => col.sortKey && onSort(col.sortKey)}
            onKeyDown={(e) => {
              if (col.sortKey && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onSort(col.sortKey);
              }
            }}
            tabIndex={col.sortKey ? 0 : undefined}
            aria-label={col.sortKey ? `Sort by ${col.header}` : col.header}
          >
            {col.header}
            <SortIcon sortKey={col.sortKey} sort={sort} />
          </div>
        ))}
      </div>

      {/* ── Virtualized rows ─────────────────────────────────────────────── */}
      {isLoading ? (
        // WHY match header height: skeletons must be the same height as real rows
        // so the layout doesn't shift when data arrives.
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
        // WHY inline empty state: §0.5 bans large centered empty states.
        // A single-line message at the top of the scroll area is sufficient.
        <div className="px-2 py-1 text-[11px] text-muted-foreground">
          No results. Adjust filters and apply.
        </div>
      ) : (
        // WHY overflow-auto on this div: the virtualizer needs a scrollable
        // container. This div fills remaining space and scrolls independently
        // of the sticky header above.
        <div ref={scrollRef} className="flex-1 overflow-auto">
          {/* WHY relative + explicit height: virtualizer uses absolute-positioned
              rows so the container must have the correct total height to produce
              a proper scroll thumb size in the scrollbar. */}
          <div
            style={{
              height: rowVirtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {rowVirtualizer.getVirtualItems().map((vRow) => {
              const row = rows[vRow.index];
              return (
                <div
                  key={vRow.key}
                  // WHY absolute + transform: virtualizer uses transform to
                  // position rows without triggering layout recalculation on scroll.
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
                    // WHY zebra striping: even rows get a barely-perceptible background tint (2% white).
                    // Institutional pattern (Bloomberg, Refinitiv) — helps the eye track across wide rows
                    // without needing full-width horizontal rules. The hover tint is slightly stronger
                    // than the zebra tint so the hovered row always reads as active.
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
                  {COLS.map((col) => (
                    <div
                      key={col.header}
                      role="cell"
                      className={cn(
                        "shrink-0 px-2 overflow-hidden",
                        col.align === "right" ? "flex justify-end" : col.align === "center" ? "flex justify-center" : "flex justify-start",
                      )}
                      style={{ width: col.width, minWidth: col.width }}
                    >
                      {col.render(row)}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
