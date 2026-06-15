/**
 * components/instrument/financials/PeerComparisonTable.tsx — peer relative-value panel
 * (Wave-2 Financials redesign, scope item 4 — first-class peer comparison).
 *
 * WHY THIS REWRITE: the previous table consumed the legacy n=5 peers slice
 * (prop-drilled from useFinancialsSidebarData) and burned two of its six
 * columns on low-information fields: NAME (truncated anyway) + SECTOR (the
 * same string on every row — the endpoint selects peers WITHIN one
 * industry). The Wave-1 backend upgrade returns 8 peers with `last_price` +
 * `change_pct`, which turns this into a real relative-value board: price
 * action (LAST / DAY %) next to valuation (MCAP / P/E) next to momentum
 * (1Y RET) — the Bloomberg "RV" scan in one glance.
 *
 * WHAT CHANGED vs the old table:
 *   - self-fetches via usePeers (n=8, upgraded shape) — see usePeers.ts for
 *     why the fetcher lives here and not in lib/api/instruments.ts;
 *   - columns: TICKER | NAME | LAST | DAY % | MKT CAP | P/E | 1Y RET
 *     (SECTOR dropped — constant per the module note above; the shared
 *     industry now renders once in the header meta where it belongs);
 *   - the subject row now shows REAL last/day% (from the page quote prop)
 *     instead of the old triple of em-dashes;
 *   - 22px rows (DESIGN_SYSTEM --data-row-height) + uniform PanelHeader.
 *
 * WHAT WAS KEPT: self-row-first ordering, bg-muted/30 self highlight + ◆
 * marker, row click → router.push (rows are divs, not anchors), the
 * "{n} peers · click row to navigate" footer, shape-matched skeleton.
 *
 * WHO USES IT: FinancialsTab.tsx — left column, after the earnings panel.
 * DATA SOURCE: usePeers → S9 GET /v1/instruments/{id}/peers?n=8 (Wave-1).
 */

"use client";
// WHY "use client": useRouter + the usePeers TanStack hook are browser-only.

import { useRouter } from "next/navigation";

import { PanelHeader } from "./PanelHeader";
import { SortableHeaderCell } from "./SortableHeaderCell";
import { useSortableRows, type SortAccessor } from "./useSortableRows";
import { usePeers, type PeerRowV2 } from "./usePeers";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMarketCap, formatPercent, formatPercentDirect, formatPrice } from "@/lib/utils";
import type { Fundamentals, Quote } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface PeerComparisonTableProps {
  /** Subject instrument fundamentals — identity + MCAP/P-E for the self row. */
  readonly fundamentals: Fundamentals | null | undefined;
  /** Live quote — supplies the self row's LAST + DAY % (peers carry their own). */
  readonly quote: Quote | null | undefined;
  /** Keys the peers fetch. Empty string disables it (page bundle not resolved). */
  readonly instrumentId: string;
}

// ── Layout ────────────────────────────────────────────────────────────────────
// One shared template so the header row and data rows can never drift out of
// alignment (the old table repeated the template string twice already; with
// 7 columns the single-constant discipline matters even more).
// Widths: ticker 64 / name flexible / last 72 / day% 64 / mcap 80 / pe 56 / 1y 64.
const GRID_TEMPLATE = "grid-cols-[64px_minmax(80px,1fr)_72px_64px_80px_56px_64px]";

// Wave-4: every column is sortable. `key` doubles as the SortableHeaderCell
// key and the accessor key below — one source of truth so they can't drift.
type PeerSortKey = "ticker" | "name" | "last" | "day" | "mcap" | "pe" | "ret1y";

const COLS: Array<{ key: PeerSortKey; label: string; align: "left" | "right" }> = [
  { key: "ticker", label: "TICKER", align: "left" },
  { key: "name", label: "NAME", align: "left" },
  { key: "last", label: "LAST", align: "right" },
  { key: "day", label: "DAY %", align: "right" },
  { key: "mcap", label: "MKT CAP", align: "right" },
  { key: "pe", label: "P/E", align: "right" },
  { key: "ret1y", label: "1Y RET", align: "right" },
];

// Value extractors for sorting the PEER rows (self stays pinned, see below).
const PEER_ACCESSORS: Record<PeerSortKey, SortAccessor<PeerRowV2>> = {
  ticker: (p) => p.ticker ?? null,
  name: (p) => p.name ?? null,
  last: (p) => p.last_price ?? null,
  day: (p) => p.change_pct ?? null,
  mcap: (p) => p.market_cap ?? null,
  pe: (p) => p.pe_ratio ?? null,
  ret1y: (p) => p.return_1y ?? null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Signed colour class for a percentage value; muted dash styling when null. */
function pctClass(v: number | null): string {
  if (v == null) return "text-muted-foreground/40";
  return v >= 0 ? "text-positive" : "text-negative";
}

/** 1Y return arrives as a DECIMAL (0.57 = +57%) → formatPercent handles ×100. */
function fmtReturn1y(v: number | null): string {
  return v == null ? "—" : formatPercent(v);
}

/** Day change arrives ALREADY-PERCENT (1.61 = +1.61%) → formatPercentDirect. */
function fmtDayPct(v: number | null): string {
  return v == null ? "—" : formatPercentDirect(v, 2);
}

// ── Self-row builder ──────────────────────────────────────────────────────────

/**
 * The subject instrument rendered in the same PeerRowV2 shape as the peers.
 * LAST/DAY% come from the live page quote (the peers endpoint doesn't echo
 * the subject); 1Y RET stays null — it would need an extra OHLCV fetch and
 * is one click away on the Quote tab.
 */
function buildSelfRow(fundamentals: Fundamentals, quote: Quote | null | undefined): PeerRowV2 {
  return {
    instrument_id: fundamentals.instrument_id,
    ticker: fundamentals.ticker,
    name: fundamentals.name,
    market_cap: fundamentals.market_cap ?? null,
    pe_ratio: fundamentals.pe_ratio ?? null,
    return_1y: null,
    change_pct: quote?.change_pct ?? null,
    last_price: quote?.price ?? null,
  };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PeerComparisonTable({
  fundamentals,
  quote,
  instrumentId,
}: PeerComparisonTableProps) {
  const router = useRouter();
  const peersQuery = usePeers(instrumentId);

  // Wave-4: sort ONLY the peer rows. The subject ("self") row stays PINNED at
  // the top regardless of sort — a relative-value board exists to compare
  // peers *against* the subject, so the subject must always be the anchor the
  // eye returns to (the same reason it carries the ◆ marker + highlight). The
  // default order is the endpoint's market-cap ranking until a header click.
  const peerRowsRaw = peersQuery.data?.peers ?? [];
  const { sortedRows: sortedPeers, sort, toggleSort } = useSortableRows<PeerRowV2, PeerSortKey>({
    rows: peerRowsRaw,
    accessors: PEER_ACCESSORS,
    // Text columns sort A→Z first; the numeric value/price/% columns biggest-first.
    defaultDirections: { ticker: "asc", name: "asc" },
  });

  // Cold first fetch → shape-matched skeleton: header band + 9 row bars
  // (self + 8 peers) at the 22px row rhythm so the panel doesn't jump when
  // data lands (DESIGN_SYSTEM §6.2 — skeletons mirror the final layout).
  if (peersQuery.isLoading) {
    return (
      <div role="status" aria-label="Loading peer comparison" className="space-y-1 border-t border-border px-2 py-1">
        <Skeleton className="h-5 w-1/3 rounded-[2px]" />
        {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((row) => (
          <Skeleton key={row} className="h-4 w-full rounded-[1px]" />
        ))}
      </div>
    );
  }

  const selfRow = fundamentals ? buildSelfRow(fundamentals, quote) : null;
  // Pin self first, then the SORTED peers (self is excluded from the sort).
  const peerRows = peerRowsRaw;
  const allRows: Array<PeerRowV2 & { isSelf: boolean }> = [
    ...(selfRow ? [{ ...selfRow, isSelf: true }] : []),
    ...sortedPeers.map((p) => ({ ...p, isSelf: false })),
  ];

  if (allRows.length === 0) {
    return (
      <div className="border-t border-border">
        <PanelHeader label="PEER COMPARISON" />
        <div className="flex items-center justify-center py-4">
          <span className="font-mono text-[11px] text-muted-foreground">No peer data available</span>
        </div>
      </div>
    );
  }

  return (
    <div data-table-grid className="w-full border-t border-border">
      {/* Header — the shared industry renders ONCE here (it used to repeat
          in every row's SECTOR cell, which carried zero information). */}
      <PanelHeader
        label="PEER COMPARISON"
        meta={
          peerRows.length > 0
            ? `${peersQuery.data?.industry ?? "same industry"} · by market cap`
            : undefined
        }
      />

      {/* Column headers — same grid template as data rows (alignment lock).
          Wave-4: each header is now click-to-sort (SortableHeaderCell, div
          mode for this CSS-grid layout). Sorting re-ranks the PEER rows; the
          subject row stays pinned on top. */}
      <div className={`grid ${GRID_TEMPLATE} border-b border-border bg-background/60`} role="row">
        {COLS.map((col) => (
          <SortableHeaderCell
            key={col.key}
            as="div"
            label={col.label}
            align={col.align}
            active={sort.key === col.key}
            direction={sort.direction}
            onSort={() => toggleSort(col.key)}
          />
        ))}
      </div>

      {/* Data rows — 22px (--data-row-height), self first then 8 peers. */}
      {allRows.map((row) => (
        <div
          key={row.instrument_id}
          className={`grid ${GRID_TEMPLATE} border-b border-border/40 last:border-b-0 ${
            row.isSelf
              ? // Self highlight: locate the subject instantly in a 9-row scan.
                "bg-muted/30"
              : "cursor-pointer transition-colors hover:bg-muted/10"
          }`}
          // Click only on peer rows — clicking self would reload the same page.
          onClick={
            row.isSelf
              ? undefined
              : () => router.push(`/instruments/${encodeURIComponent(row.ticker)}`)
          }
          // Keyboard path for the click affordance (rows are divs, not links).
          onKeyDown={
            row.isSelf
              ? undefined
              : (e) => {
                  if (e.key === "Enter") {
                    router.push(`/instruments/${encodeURIComponent(row.ticker)}`);
                  }
                }
          }
          tabIndex={row.isSelf ? undefined : 0}
          role="row"
          aria-label={row.isSelf ? `${row.ticker} (current)` : `Navigate to ${row.ticker}`}
          data-testid={`peer-row-${row.ticker}`}
        >
          {/* TICKER — primary-tinted for navigable peers, plain for self. */}
          <div className="flex h-[22px] items-center px-2">
            <span
              className={`font-mono text-[11px] font-semibold tabular-nums ${
                row.isSelf ? "text-foreground" : "text-primary"
              }`}
            >
              {row.ticker}
            </span>
            {row.isSelf && (
              <span className="ml-1 font-mono text-[8px] text-muted-foreground/60">◆</span>
            )}
          </div>

          {/* NAME — single line, truncates under pressure (min-w-0 enables it). */}
          <div className="flex h-[22px] min-w-0 items-center px-2">
            <span className="truncate font-mono text-[10px] text-muted-foreground">{row.name}</span>
          </div>

          {/* LAST — live price (peers: from endpoint; self: page quote). */}
          <div className="flex h-[22px] items-center justify-end px-2">
            <span className="font-mono text-[11px] tabular-nums text-foreground">
              {row.last_price != null ? formatPrice(row.last_price) : "—"}
            </span>
          </div>

          {/* DAY % — signed + colour-coded (already-percent input). */}
          <div className="flex h-[22px] items-center justify-end px-2">
            <span className={`font-mono text-[11px] tabular-nums ${pctClass(row.change_pct)}`}>
              {fmtDayPct(row.change_pct)}
            </span>
          </div>

          {/* MKT CAP */}
          <div className="flex h-[22px] items-center justify-end px-2">
            <span className="font-mono text-[11px] tabular-nums text-foreground">
              {formatMarketCap(row.market_cap)}
            </span>
          </div>

          {/* P/E */}
          <div className="flex h-[22px] items-center justify-end px-2">
            <span className="font-mono text-[11px] tabular-nums text-foreground">
              {row.pe_ratio != null ? row.pe_ratio.toFixed(1) : "—"}
            </span>
          </div>

          {/* 1Y RET — decimal input, colour-coded. Self renders "—" by design. */}
          <div className="flex h-[22px] items-center justify-end px-2">
            <span className={`font-mono text-[11px] tabular-nums ${pctClass(row.return_1y)}`}>
              {fmtReturn1y(row.return_1y)}
            </span>
          </div>
        </div>
      ))}

      {/* Footer — row count + interaction hint (kept from the old table). */}
      <div className="flex items-center border-t border-border bg-background/40 px-2 py-1">
        <span className="font-mono text-[9px] text-muted-foreground/50">
          {peerRows.length} peer{peerRows.length !== 1 ? "s" : ""} · click row to navigate
        </span>
      </div>
    </div>
  );
}
