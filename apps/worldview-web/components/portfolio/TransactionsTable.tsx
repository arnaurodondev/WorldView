/**
 * components/portfolio/TransactionsTable.tsx — Transaction history with rich filter bar
 *
 * WHY THIS EXISTS: Traders need to review their execution history to verify fills,
 * assess average-cost basis accuracy, and track dividend income. Extracted from
 * portfolio/page.tsx as a standalone component so it can be tested independently.
 *
 * WHY 8 COLUMNS: Date | Type | Class | Ticker | Qty | Price | Total | Fee covers
 * the full picture of a trade execution without becoming wider than a typical panel.
 * The asset-class badge (PLAN-0053 T-D-4-02) was added between Type and Ticker.
 *
 * WHY DIVIDEND row shows "—" for Qty and Price: a dividend is an income event,
 * not a share purchase/sale. Qty and Price are meaningless for dividends; the
 * relevant amount is in the Total column (using tx.amount).
 *
 * PLAN-0059 F-1 — Migrated to DataTable primitive. react-window removed;
 * DataTable (@tanstack/react-virtual) handles virtualisation natively.
 * Column definitions extracted to transaction-columns.tsx for isolated testing.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Transactions tab
 * DATA SOURCE: getTransactions() via parent page
 * DESIGN REFERENCE: PRD-0031 §8.4 Transactions Table; PLAN-0051 Wave A
 */

"use client";
// WHY "use client": every interactive piece requires browser-only behaviour:
// useState (filter state), useEffect (debounce timer), HTML <input type=date>
// rendering, and synchronous DOM document.createElement for the CSV download.

import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/utils";
import { exportToCsv, todayDateStamp } from "@/lib/csv-export";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { DataTable } from "@/components/ui/data-table";
import { makeTransactionColumns, rowTotal } from "./transaction-columns";
import type { Transaction } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TransactionsTableProps {
  transactions: Transaction[];
  /**
   * @deprecated F-205 (QA iter-2): the gateway / S1 now populate ``ticker``
   * directly on every transaction. The fallback lookup is retained ONLY so
   * existing call sites that still pass the map don't break — it's no longer
   * required for a correct render. New consumers MUST omit this prop.
   *
   * Historical context: BP-262 added this workaround when ``tx.ticker`` was
   * always empty. The server-side enrichment supersedes it.
   */
  tickerByInstrumentId?: Record<string, string | null | undefined>;
}

// WHY "ALL" exists as a literal value: avoids special-casing null in filter
// logic. Every tx.type matches "ALL"; BUY matches only BUY transactions, etc.
type FilterType = "ALL" | "BUY" | "SELL" | "DIVIDEND";

// WHY a discriminated currency literal "ALL" for the same reason:
// the filter compares tx.currency to the value; "ALL" short-circuits.
type CurrencyFilter = "ALL" | "USD" | "EUR";

// Threshold above which DataTable activates its built-in react-virtual
// path. Below this number the synchronous render is faster (no
// ResizeObserver overhead) and produces nicer accessibility output.
const VIRTUALISATION_THRESHOLD = 200;

/**
 * Inline debounce — returns a value that lags the input by `delayMs`.
 *
 * WHY local (not the shared hooks/useDebounce.ts): this file is intentionally
 * dependency-light. The inline version is 8 lines and entirely self-explanatory.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

// ── Filter-bar styling ───────────────────────────────────────────────────────

// WHY a shared className constant: every input in the filter bar — date,
// text, number, datalist trigger — shares the exact same height, padding,
// font, border, and focus colour. A constant prevents drift when we add
// another input.
const INPUT_CLS =
  "h-6 px-2 text-[11px] font-mono bg-card border border-border rounded-[2px] " +
  "text-foreground placeholder:text-muted-foreground focus:outline-none " +
  "focus:border-primary focus:ring-1 focus:ring-primary/30";

// ── TransactionsTable ─────────────────────────────────────────────────────────

export function TransactionsTable({
  transactions,
  tickerByInstrumentId,
}: TransactionsTableProps) {
  // ── Column definitions ────────────────────────────────────────────────────
  // WHY useMemo: makeTransactionColumns closes over tickerByInstrumentId.
  // Re-creating on every render would produce new column-def references,
  // making TanStack Table re-initialise its column model on every keystroke.
  const columns = useMemo(
    () => makeTransactionColumns(tickerByInstrumentId),
    [tickerByInstrumentId],
  );

  // ── Filter state ──────────────────────────────────────────────────────────
  const [activeFilter, setActiveFilter] = useState<FilterType>("ALL");
  const [fromDate, setFromDate] = useState<string>(""); // YYYY-MM-DD or ""
  const [toDate, setToDate] = useState<string>("");
  const [tickerFilter, setTickerFilter] = useState<string>("");
  const [currencyFilter, setCurrencyFilter] = useState<CurrencyFilter>("ALL");
  const [minAmount, setMinAmount] = useState<string>(""); // string so blank ≠ 0
  const [maxAmount, setMaxAmount] = useState<string>("");
  const [searchRaw, setSearchRaw] = useState<string>("");

  // Debounce free-text search so we don't recompute the filtered list on
  // every keystroke. 200 ms feels instantaneous while collapsing keystroke
  // bursts into one pass.
  const search = useDebouncedValue(searchRaw, 200);

  // TODO(PLAN-0051 / backend): the original spec calls for a "market" filter.
  // Transaction has no market/exchange/MIC field today — currency is a proxy.

  // ── Filter active? ────────────────────────────────────────────────────────
  const anyFilterActive =
    activeFilter !== "ALL" ||
    fromDate !== "" ||
    toDate !== "" ||
    tickerFilter.trim() !== "" ||
    currencyFilter !== "ALL" ||
    minAmount !== "" ||
    maxAmount !== "" ||
    searchRaw !== "";

  function clearFilters() {
    setActiveFilter("ALL");
    setFromDate("");
    setToDate("");
    setTickerFilter("");
    setCurrencyFilter("ALL");
    setMinAmount("");
    setMaxAmount("");
    setSearchRaw("");
  }

  // ── Ticker datalist ───────────────────────────────────────────────────────
  const tickerOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const tx of transactions) {
      const t = tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || "";
      if (t) seen.add(t);
    }
    return Array.from(seen).sort();
  }, [transactions, tickerByInstrumentId]);

  // ── Empty state guard ─────────────────────────────────────────────────────
  if (transactions.length === 0) {
    return (
      <InlineEmptyState message="No transactions yet. Connect a brokerage to import activity, or use Add Position to record a trade manually." />
    );
  }

  // ── Sort + filter pipeline ────────────────────────────────────────────────
  // WHY sort newest-first client-side: the API returns insertion order which
  // may not match execution order. Traders always review most-recent activity first.
  const sorted = [...transactions].sort((a, b) =>
    b.executed_at.localeCompare(a.executed_at),
  );

  const minAmt = minAmount === "" ? NaN : Number(minAmount);
  const maxAmt = maxAmount === "" ? NaN : Number(maxAmount);
  const tickerLower = tickerFilter.trim().toLowerCase();
  const searchLower = search.trim().toLowerCase();

  const filtered = sorted.filter((tx) => {
    if (activeFilter !== "ALL" && tx.type !== activeFilter) return false;

    // WHY string comparison for dates: avoids timezone shifts that would drop
    // a tx executed at 00:30 UTC out of "today's" range for a PST user.
    if (fromDate && tx.executed_at.slice(0, 10) < fromDate) return false;
    if (toDate && tx.executed_at.slice(0, 10) > toDate) return false;

    if (tickerLower) {
      const t = (
        tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || ""
      ).toLowerCase();
      if (!t.includes(tickerLower)) return false;
    }

    if (currencyFilter !== "ALL" && tx.currency !== currencyFilter) return false;

    // Amount range applies to the row's "total" so the filter behaves the way
    // the user reads the Total column.
    const total = rowTotal(tx);
    if (!Number.isNaN(minAmt) && total < minAmt) return false;
    if (!Number.isNaN(maxAmt) && total > maxAmt) return false;

    if (searchLower) {
      const tickerHaystack = (
        tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || ""
      ).toLowerCase();
      const matches =
        tickerHaystack.includes(searchLower) ||
        tx.type.toLowerCase().includes(searchLower) ||
        (tx.notes ?? "").toLowerCase().includes(searchLower);
      if (!matches) return false;
    }

    return true;
  });

  // ── Totals row ────────────────────────────────────────────────────────────
  let buyCost = 0;
  let sellProceeds = 0;
  let divIncome = 0;
  for (const tx of filtered) {
    if (tx.type === "BUY") buyCost += tx.quantity * tx.price;
    else if (tx.type === "SELL") sellProceeds += tx.quantity * tx.price;
    else if (tx.type === "DIVIDEND") divIncome += tx.amount ?? 0;
  }

  const filterButtons: { label: string; value: FilterType }[] = [
    { label: "All", value: "ALL" },
    { label: "BUY", value: "BUY" },
    { label: "SELL", value: "SELL" },
    { label: "DIV", value: "DIVIDEND" },
  ];

  // ── CSV export ────────────────────────────────────────────────────────────
  function handleExportCsv() {
    exportToCsv<Transaction>({
      filenameStem: `transactions-${todayDateStamp()}`,
      rows: filtered,
      columns: [
        { header: "Date", accessor: (r) => r.executed_at },
        { header: "Type", accessor: (r) => r.type },
        {
          header: "Ticker",
          accessor: (r) =>
            r.ticker || tickerByInstrumentId?.[r.instrument_id] || "",
        },
        { header: "Quantity", accessor: (r) => r.quantity },
        { header: "Price", accessor: (r) => r.price },
        { header: "Total", accessor: (r) => rowTotal(r) },
        { header: "Fee", accessor: (r) => r.fee },
        { header: "Currency", accessor: (r) => r.currency },
      ],
    });
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-0">
      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap h-auto items-center gap-1 gap-y-1 border-b border-border px-2 py-1 shrink-0">
        {filterButtons.map(({ label, value }) => (
          <button
            key={value}
            aria-pressed={activeFilter === value}
            aria-label={`Show ${value === "ALL" ? "all transactions" : value + " transactions"}`}
            className={cn(
              "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
              activeFilter === value
                ? "bg-primary/10 border-primary text-primary"
                : "bg-transparent border-border text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setActiveFilter(value)}
          >
            {label}
          </button>
        ))}

        <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          From
          <input
            type="date"
            aria-label="Filter from date"
            className={INPUT_CLS}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          To
          <input
            type="date"
            aria-label="Filter to date"
            className={INPUT_CLS}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </label>

        <input
          type="text"
          aria-label="Filter by ticker"
          placeholder="Ticker"
          list="transactions-ticker-list"
          className={cn(INPUT_CLS, "w-20")}
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
        />
        <datalist id="transactions-ticker-list">
          {tickerOptions.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>

        <select
          aria-label="Filter by currency"
          className={cn(INPUT_CLS, "w-16 cursor-pointer")}
          value={currencyFilter}
          onChange={(e) => setCurrencyFilter(e.target.value as CurrencyFilter)}
        >
          <option value="ALL">All</option>
          <option value="USD">USD</option>
          <option value="EUR">EUR</option>
        </select>

        <input
          type="number"
          aria-label="Minimum amount"
          placeholder="Min $"
          inputMode="decimal"
          className={cn(INPUT_CLS, "w-16")}
          value={minAmount}
          onChange={(e) => setMinAmount(e.target.value)}
        />
        <input
          type="number"
          aria-label="Maximum amount"
          placeholder="Max $"
          inputMode="decimal"
          className={cn(INPUT_CLS, "w-16")}
          value={maxAmount}
          onChange={(e) => setMaxAmount(e.target.value)}
        />

        <input
          type="search"
          aria-label="Search transactions"
          placeholder="Search…"
          className={cn(INPUT_CLS, "w-32")}
          value={searchRaw}
          onChange={(e) => setSearchRaw(e.target.value)}
        />

        {anyFilterActive && (
          <button
            type="button"
            onClick={clearFilters}
            className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground transition-colors"
          >
            Clear filters
          </button>
        )}

        <button
          type="button"
          aria-label="Export transactions as CSV"
          onClick={handleExportCsv}
          className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground transition-colors"
        >
          Export CSV
        </button>

        <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
          {filtered.length} / {transactions.length}
        </span>
      </div>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      {/*
       * WHY DataTable (not raw <table>): provides uniform density, multi-column
       * sort, copy-as-TSV, sticky header, column resize, and built-in virtualisation
       * (TanStack react-virtual) for free. Column defs live in transaction-columns.tsx
       * so they can be unit-tested independently.
       *
       * WHY data-testid="transactions-virtualised" wrapper: existing tests assert
       * that this testid is present when filtered.length > VIRTUALISATION_THRESHOLD
       * and absent when not. The conditional wrapper preserves that contract
       * without the test needing to know about DataTable's internal virtualise prop.
       */}
      <div
        {...(filtered.length > VIRTUALISATION_THRESHOLD
          ? { "data-testid": "transactions-virtualised" }
          : {})}
        className="overflow-auto"
      >
        <DataTable
          columns={columns}
          data={filtered}
          getRowId={(tx) => tx.transaction_id}
          density="compact"
          isLoading={false}
          emptyMessage={`No${activeFilter !== "ALL" ? ` ${activeFilter}` : ""} transactions match the current filters.`}
          rowClassName={(tx) => {
            // WHY isPlaceholder check: brokerage imports include sentinel rows
            // (corporate actions) with qty=0 AND price=0. De-emphasise them
            // visually so real fills stand out. (BP-263 / F-P-028)
            const isPlaceholder = tx.type !== "DIVIDEND" && tx.quantity === 0 && tx.price === 0;
            return isPlaceholder ? "text-muted-foreground/50" : undefined;
          }}
          virtualize={filtered.length > VIRTUALISATION_THRESHOLD}
        />
      </div>

      {/* ── Totals row ──────────────────────────────────────────────────── */}
      {/* WHY render outside DataTable: totals are a summary strip across all
          filtered rows — not a data row. DataTable rows map to Transaction
          entities; the totals row has a different role and a different visual
          treatment (border-t-2, condensed text). */}
      <div
        data-testid="transactions-totals"
        className="flex h-7 items-center gap-4 border-t-2 border-border bg-card px-2 shrink-0"
      >
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Totals
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          BUY cost{" "}
          <span data-testid="totals-buy" className="ml-1 text-foreground">
            {formatPrice(buyCost)}
          </span>
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          SELL proceeds{" "}
          <span data-testid="totals-sell" className="ml-1 text-foreground">
            {formatPrice(sellProceeds)}
          </span>
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          DIV income{" "}
          <span data-testid="totals-div" className="ml-1 text-foreground">
            {formatPrice(divIncome)}
          </span>
        </span>
      </div>
    </div>
  );
}
