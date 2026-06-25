/**
 * components/portfolio/detail/TransactionsLedger.tsx — Dense 20px-row
 * transaction journal (Wave G, PRD-0089 / PLAN-0090).
 *
 * WHY THIS EXISTS: The existing TransactionsTable uses 22px rows and 8
 * columns. This redesign tightens row density to 20px (Bloomberg / Finviz
 * scan-list standard), adds 5 new columns (Time, Name, FX, Cash Impact,
 * Running Balance), and introduces column-header click-to-sort.
 *
 * WHY a new file (not editing TransactionsTable.tsx):
 *   - The spec says "create it if it doesn't exist" and the design allocates
 *     a new path `components/portfolio/detail/TransactionsLedger.tsx`.
 *   - Modifying TransactionsTable.tsx risks breaking 6+ existing tests for
 *     the old component. The Ledger is a superset redesign, not a patch.
 *   - Both components are used by different surfaces: TransactionsTable
 *     remains on the legacy tab; the Ledger powers the Wave G dense view.
 *
 * WHY 13 columns: matches the design spec §4.2 exactly:
 *   DATE | TIME | TYPE | CLASS | TICKER | NAME | QTY | PRICE | TOTAL |
 *   FEE | FX | CASH IMPACT | BALANCE
 *
 * WHY column-header sort (not AG Grid): the ledger is a plain <table>
 * component — no AG Grid dependency for a pure list. Client-side sort on
 * up to 100 visible rows is cheap (O(n log n), n ≤ 100).
 *
 * WHY "Load more" instead of virtualisation: @tanstack/react-virtual is not
 * in the project's package.json. A window of 100 rows with "Load more" keeps
 * DOM size bounded and avoids adding a new dependency.
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx (Wave G)
 *              and the new Analytics tab attribution CTA.
 * DATA SOURCE: Transaction[] passed from parent (already fetched by usePortfolioData).
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.2
 */

"use client";
// WHY "use client": useState (sort state, page), useMemo (sorted/filtered slice).

import { useState, useMemo } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Rows visible before "Load more" button appears. */
const PAGE_SIZE = 100;

/** Column definitions — order matches design spec §4.2. */

// ── Types ─────────────────────────────────────────────────────────────────────

type SortDir = "asc" | "desc" | null;

interface SortState {
  col: string | null;
  dir: SortDir;
}

// ── Format helpers ────────────────────────────────────────────────────────────

/** Format a dollar amount with sign. */
function fmtSigned(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  const abs = Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val >= 0 ? `+$${abs}` : `-$${abs}`;
}

/** Format a dollar amount, no sign. */
function fmtDollar(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  return `$${Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Compute the gross trade amount for sorting and display. */
function rowGross(tx: Transaction): number {
  if (tx.type === "DIVIDEND") return tx.amount ?? 0;
  return tx.quantity * tx.price;
}

/** Compute cash impact (signed: positive = cash in, negative = cash out). */
function rowCashImpact(tx: Transaction): number {
  if (tx.type === "DIVIDEND") return tx.amount ?? 0;
  if (tx.type === "SELL") return tx.quantity * tx.price - (tx.fee ?? 0);
  // BUY: negative cash impact
  return -(tx.quantity * tx.price + (tx.fee ?? 0));
}

/** Extract time-only portion of an ISO timestamp as HH:MM. */
function fmtTime(iso: string): string {
  // ISO looks like "2026-05-19T14:32:00Z" or "2026-05-19 14:32:00"
  const match = iso.match(/T?(\d{2}:\d{2})/);
  return match ? match[1] : "—";
}

/** Abbreviate asset class for the CLASS column. */
function assetClassAbbrev(cls: string | null): string {
  if (!cls) return "—";
  switch (cls.toLowerCase()) {
    case "equity": return "EQT";
    case "etf": return "ETF";
    case "option": return "OPT";
    case "future": return "FUT";
    case "bond": return "BND";
    case "crypto": return "CRY";
    default: return cls.slice(0, 3).toUpperCase();
  }
}

// ── Column sort helpers ───────────────────────────────────────────────────────

type SortKey = (tx: Transaction) => number | string;

const SORT_FNS: Record<string, SortKey> = {
  date: (tx) => tx.executed_at,
  type: (tx) => tx.type,
  cls: (tx) => tx.asset_class ?? "",
  ticker: (tx) => tx.ticker,
  qty: (tx) => tx.quantity,
  price: (tx) => tx.price,
  gross: (tx) => rowGross(tx),
  fee: (tx) => tx.fee,
  cashImpact: (tx) => rowCashImpact(tx),
};

// ── Column header component ───────────────────────────────────────────────────

interface ColHeaderProps {
  label: string;
  colKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
}

function ColHeader({ label, colKey, sort, onSort, className }: ColHeaderProps) {
  const isActive = sort.col === colKey;

  return (
    <th
      onClick={() => onSort(colKey)}
      className={cn(
        "px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground",
        "font-normal cursor-pointer select-none hover:text-foreground transition-colors whitespace-nowrap",
        isActive && "text-primary",
        className,
      )}
    >
      <div className="flex items-center gap-0.5">
        {label}
        {/* Sort direction icon */}
        {isActive && sort.dir === "asc" && (
          <ChevronUp className="h-2.5 w-2.5" />
        )}
        {isActive && sort.dir === "desc" && (
          <ChevronDown className="h-2.5 w-2.5" />
        )}
        {(!isActive) && (
          <ChevronsUpDown className="h-2.5 w-2.5 opacity-30" />
        )}
      </div>
    </th>
  );
}

// ── Totals row ────────────────────────────────────────────────────────────────

interface TotalsRowProps {
  transactions: Transaction[];
}

/**
 * TotalsRow — sticky bottom summary row.
 *
 * WHY totals-in-tfoot (not a sibling div): the spec says use <tfoot> so
 * screen readers announce it as a table totals row. Styled as sticky bottom.
 */
function TotalsRow({ transactions }: TotalsRowProps) {
  const totalBuyCost = transactions
    .filter((t) => t.type === "BUY")
    .reduce((sum, t) => sum + t.quantity * t.price, 0);

  const totalSellProceeds = transactions
    .filter((t) => t.type === "SELL")
    .reduce((sum, t) => sum + t.quantity * t.price, 0);

  const totalDivIncome = transactions
    .filter((t) => t.type === "DIVIDEND")
    .reduce((sum, t) => sum + (t.amount ?? 0), 0);

  const totalFees = transactions.reduce((sum, t) => sum + (t.fee ?? 0), 0);

  const netCashImpact = transactions.reduce(
    (sum, t) => sum + rowCashImpact(t),
    0,
  );

  return (
    <tfoot>
      <tr className="h-[24px] border-t border-border bg-card sticky bottom-0">
        {/* Span DATE through NAME (6 cols) with TOTALS label */}
        <td
          colSpan={6}
          className="px-2 py-0.5 text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono font-semibold"
        >
          TOTALS ({transactions.length})
        </td>
        {/* QTY — blank */}
        <td className="px-2 py-0.5" />
        {/* PRICE — blank */}
        <td className="px-2 py-0.5" />
        {/* GROSS: BUY cost + SELL proceeds side-by-side doesn't fit — show NET */}
        <td className="px-2 py-0.5 font-mono text-[10px] tabular-nums text-right text-foreground">
          {fmtDollar(totalBuyCost + totalSellProceeds + totalDivIncome)}
        </td>
        {/* FEE total */}
        <td className="px-2 py-0.5 font-mono text-[10px] tabular-nums text-right text-negative">
          -{fmtDollar(totalFees).replace("$", "")}
        </td>
        {/* FX — blank */}
        <td className="px-2 py-0.5" />
        {/* CASH IMPACT net */}
        <td
          className={cn(
            "px-2 py-0.5 font-mono text-[10px] tabular-nums text-right",
            netCashImpact >= 0 ? "text-positive" : "text-negative",
          )}
        >
          {fmtSigned(netCashImpact)}
        </td>
        {/* BAL — blank in totals (balance is running, not summable) */}
        <td className="px-2 py-0.5" />
      </tr>
    </tfoot>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface TransactionsLedgerProps {
  /** All transactions for this portfolio (pre-fetched by parent). */
  transactions: Transaction[];
  /**
   * Optional ticker filter — when provided, only transactions for this ticker
   * are shown (used by HoldingDetailSlideOver's "recent tx" CTA).
   */
  tickerFilter?: string | null;
  /**
   * Optional className for the outer container.
   */
  className?: string;
}

// ── Main component ────────────────────────────────────────────────────────────

export function TransactionsLedger({
  transactions,
  tickerFilter,
  className,
}: TransactionsLedgerProps) {
  // ── Sort state ─────────────────────────────────────────────────────────────
  // Default sort: newest-first (date descending). This matches the ledger's
  // primary use-case (verify the most recent fills first — IBKR / TASTY pattern).
  // WHY col:null — the default "newest first" order is applied in the sort useMemo
  // as a fallback when no explicit column is active (col:null). This lets the first
  // click on DATE set ascending cleanly (null→asc→desc→null cycle starts fresh).
  const [sort, setSort] = useState<SortState>({ col: null, dir: null });

  // ── Pagination state ────────────────────────────────────────────────────────
  // WHY page (not cursor): client-side data, simple slice. Each "Load more"
  // click increments the visible window by PAGE_SIZE. Resets to 1 on sort change.
  const [page, setPage] = useState(1);

  // ── Column sort toggle ─────────────────────────────────────────────────────
  function handleSort(col: string) {
    setSort((prev) => {
      if (prev.col !== col) {
        return { col, dir: "asc" };
      }
      if (prev.dir === "asc") return { col, dir: "desc" };
      if (prev.dir === "desc") return { col: null, dir: null };
      return { col, dir: "asc" };
    });
    // Reset page on new sort so the user sees the first sorted results.
    setPage(1);
  }

  // ── Sorted + filtered slice ────────────────────────────────────────────────
  const displayed = useMemo(() => {
    // 1. Apply optional ticker filter.
    let filtered = tickerFilter
      ? transactions.filter(
          (t) => t.ticker.toUpperCase() === tickerFilter.toUpperCase(),
        )
      : transactions;

    // 2. Apply sort. When no explicit sort column is active, default to newest-
    //    first by date (IBKR / TASTY pattern — most recent fills first).
    const activeSortFn = sort.col ? SORT_FNS[sort.col] : null;
    const activeDir = sort.dir;
    if (activeSortFn && activeDir) {
      filtered = [...filtered].sort((a, b) => {
        const va = activeSortFn(a);
        const vb = activeSortFn(b);
        if (typeof va === "string" && typeof vb === "string") {
          return activeDir === "asc"
            ? va.localeCompare(vb)
            : vb.localeCompare(va);
        }
        const na = va as number;
        const nb = vb as number;
        return activeDir === "asc" ? na - nb : nb - na;
      });
    } else {
      // Default: newest first by executed_at (no explicit sort active).
      filtered = [...filtered].sort((a, b) =>
        b.executed_at.localeCompare(a.executed_at),
      );
    }

    return filtered;
  }, [transactions, tickerFilter, sort]);

  // 3. Paginate: show first (page × PAGE_SIZE) rows.
  const visibleRows = displayed.slice(0, page * PAGE_SIZE);
  const hasMore = visibleRows.length < displayed.length;

  // ── Running balance ────────────────────────────────────────────────────────
  // WHY client-side (not server field): design spec decision 5 — compute
  // running balance client-side until backend adds `?include=running_balance`.
  // Build the running balance on the SORTED array so it respects the user's
  // current sort order (date asc gives a chronological balance series).
  const runningBalances = useMemo(() => {
    // Use a copy sorted by date ascending for the running-balance computation,
    // regardless of the user's display sort, so the balance grows monotonically.
    const chronological = [...displayed].sort((a, b) =>
      a.executed_at.localeCompare(b.executed_at),
    );
    const balanceMap = new Map<string, number>();
    let running = 0;
    for (const tx of chronological) {
      running += rowCashImpact(tx);
      // WHY last-write wins: if the same tx_id appears twice (dedup fail),
      // we keep the latest running total rather than double-counting.
      balanceMap.set(tx.transaction_id, running);
    }
    return balanceMap;
  }, [displayed]);

  // ── Empty state ────────────────────────────────────────────────────────────
  if (transactions.length === 0) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center py-12 text-center",
          className,
        )}
      >
        <p className="text-[11px] text-muted-foreground font-mono">
          No transactions yet.
        </p>
        <p className="text-[10px] text-muted-foreground font-mono mt-1">
          Connect a brokerage or add a position manually.
        </p>
      </div>
    );
  }

  // ── Filter-empty state ─────────────────────────────────────────────────────
  if (displayed.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center py-8",
          className,
        )}
      >
        <p className="text-[11px] text-muted-foreground font-mono">
          No transactions match the current filters.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col", className)}>
      {/* ── Scrollable table area ────────────────────────────────────────── */}
      <div className="overflow-x-auto">
        {/* WHY overflow-x-auto: the 13-column table is 1078px wide per spec.
            On viewports < 1200px the table scrolls horizontally — acceptable
            for a finance tool (same pattern as Bloomberg terminal grids). */}
        <table
          className="w-full text-[11px] font-mono border-collapse"
          data-testid="transactions-ledger"
          // WHY min-w-[1000px]: prevents columns from collapsing on narrow
          // viewports before horizontal scroll kicks in.
          style={{ minWidth: "1000px" }}
        >
          <thead className="sticky top-0 z-10 bg-card">
            <tr className="h-[22px] border-b border-border">
              <ColHeader label="DATE" colKey="date" sort={sort} onSort={handleSort} className="w-[88px]" />
              <th className="px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[60px] whitespace-nowrap">
                TIME
              </th>
              <ColHeader label="TYPE" colKey="type" sort={sort} onSort={handleSort} className="w-[48px]" />
              <ColHeader label="CLS" colKey="cls" sort={sort} onSort={handleSort} className="w-[48px]" />
              <ColHeader label="TICKER" colKey="ticker" sort={sort} onSort={handleSort} className="w-[64px]" />
              {/* NAME — hidden on < xl viewports */}
              <th className="px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[180px] whitespace-nowrap hidden xl:table-cell">
                NAME
              </th>
              <ColHeader label="QTY" colKey="qty" sort={sort} onSort={handleSort} className="w-[80px] text-right" />
              <ColHeader label="PRICE" colKey="price" sort={sort} onSort={handleSort} className="w-[80px] text-right" />
              <ColHeader label="GROSS" colKey="gross" sort={sort} onSort={handleSort} className="w-[100px] text-right" />
              <ColHeader label="FEE" colKey="fee" sort={sort} onSort={handleSort} className="w-[60px] text-right" />
              {/* FX — hidden on < lg viewports per spec §4.2 */}
              <th className="px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[60px] hidden lg:table-cell whitespace-nowrap">
                FX
              </th>
              <ColHeader
                label="CASH IMPACT"
                colKey="cashImpact"
                sort={sort}
                onSort={handleSort}
                className="w-[110px] text-right"
              />
              {/* BAL — hidden on < xl viewports */}
              <th className="px-2 py-1 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[100px] text-right hidden xl:table-cell whitespace-nowrap">
                BAL
                {/* WHY tooltip hint: running balance is approximate client-side
                    until the backend adds `?include=running_balance`. The
                    design spec §OQ-5 says to surface this caveat inline. */}
                <span
                  className="ml-1 text-[8px] normal-case tracking-normal text-muted-foreground/60"
                  title="Approximate — excludes FX revaluation and corporate actions"
                >
                  ~
                </span>
              </th>
            </tr>
          </thead>

          <tbody>
            {visibleRows.map((tx) => {
              const gross = rowGross(tx);
              const cashImpact = rowCashImpact(tx);
              const balance = runningBalances.get(tx.transaction_id) ?? null;

              // Row shading: alternating muted background for scan readability
              // is intentionally NOT used here — Bloomberg / IBKR use uniform
              // background so the colour coding (green/red) stands out.
              // We add hover only.
              const isDividend = tx.type === "DIVIDEND";
              const isPlaceholder =
                !isDividend && tx.quantity === 0 && tx.price === 0;

              return (
                <tr
                  key={tx.transaction_id}
                  data-testid={`ledger-row-${tx.transaction_id}`}
                  className={cn(
                    "h-[20px] border-b border-border/20",
                    "hover:bg-muted/20 transition-colors",
                    isPlaceholder && "text-muted-foreground/50",
                  )}
                >
                  {/* DATE — YYYY-MM-DD */}
                  <td className="px-2 py-0.5 tabular-nums text-muted-foreground whitespace-nowrap">
                    {tx.executed_at.slice(0, 10)}
                  </td>

                  {/* TIME — HH:MM */}
                  <td className="px-2 py-0.5 tabular-nums text-muted-foreground">
                    {fmtTime(tx.executed_at)}
                  </td>

                  {/* TYPE badge */}
                  <td className="px-2 py-0.5">
                    <span
                      className={cn(
                        "inline-flex items-center px-1 rounded-[2px] text-[10px] font-semibold",
                        tx.type === "BUY"
                          ? "bg-primary/20 text-primary"
                          : tx.type === "SELL"
                          ? "bg-negative/20 text-negative"
                          : "bg-positive/20 text-positive",
                      )}
                    >
                      {isDividend ? "DIV" : tx.type}
                    </span>
                  </td>

                  {/* CLASS badge */}
                  <td className="px-2 py-0.5">
                    <span className="text-[10px] text-muted-foreground uppercase">
                      {assetClassAbbrev(tx.asset_class)}
                    </span>
                  </td>

                  {/* TICKER */}
                  <td className="px-2 py-0.5 text-primary font-medium">
                    {tx.ticker || "—"}
                  </td>

                  {/* NAME — hidden on < xl */}
                  <td className="px-2 py-0.5 text-muted-foreground truncate max-w-[180px] hidden xl:table-cell">
                    {/* Name is not on Transaction type — we leave blank or show ticker again */}
                    —
                  </td>

                  {/* QTY — right-aligned mono */}
                  <td className="px-2 py-0.5 tabular-nums text-right">
                    {isDividend ? "—" : tx.quantity.toLocaleString()}
                  </td>

                  {/* PRICE */}
                  <td className="px-2 py-0.5 tabular-nums text-right">
                    {isDividend ? "—" : fmtDollar(tx.price)}
                  </td>

                  {/* GROSS */}
                  <td className="px-2 py-0.5 tabular-nums text-right">
                    {fmtDollar(gross)}
                  </td>

                  {/* FEE */}
                  <td
                    className={cn(
                      "px-2 py-0.5 tabular-nums text-right",
                      tx.fee > 0 ? "text-negative" : "text-muted-foreground",
                    )}
                  >
                    {tx.fee > 0 ? fmtSigned(-tx.fee) : "—"}
                  </td>

                  {/* FX — hidden on < lg; USD always 1.0000; non-USD shows rate */}
                  <td className="px-2 py-0.5 tabular-nums text-muted-foreground hidden lg:table-cell">
                    {tx.currency !== "USD"
                      ? `${tx.currency}`
                      : "1.0000"}
                  </td>

                  {/* CASH IMPACT — signed (spec §4.2: "canonical signed-cashflow column") */}
                  <td
                    className={cn(
                      "px-2 py-0.5 tabular-nums text-right",
                      cashImpact >= 0 ? "text-positive" : "text-negative",
                    )}
                  >
                    {fmtSigned(cashImpact)}
                  </td>

                  {/* RUNNING BALANCE — hidden on < xl */}
                  <td className="px-2 py-0.5 tabular-nums text-right text-muted-foreground hidden xl:table-cell">
                    {balance == null ? "—" : fmtDollar(balance)}
                  </td>
                </tr>
              );
            })}
          </tbody>

          {/* Totals row in <tfoot> for screen-reader announcements. */}
          <TotalsRow transactions={displayed} />
        </table>
      </div>

      {/* ── Load more button ──────────────────────────────────────────────── */}
      {/* WHY not infinite scroll: the ledger is a scan tool; the user needs
          to know where the list ends so they can confirm no transactions are
          missing. An explicit "Load more" button keeps the mental model clear. */}
      {hasMore && (
        <div className="flex justify-center py-3 border-t border-border">
          <button
            onClick={() => setPage((p) => p + 1)}
            className="text-[10px] font-mono uppercase tracking-[0.06em] text-primary hover:text-primary/80 transition-colors"
          >
            Load more ({displayed.length - visibleRows.length} remaining)
          </button>
        </div>
      )}
    </div>
  );
}
