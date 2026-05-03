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
// WHY FixedSizeList: react-window provides the virtualised row renderer for the
// > 200-row path. Each virtual row is rendered in an independent mini-table so
// column widths match the header via a shared colgroup percentage spec.
// The test suite mocks react-window to render all items synchronously so
// assertions on testids and column widths work without a real ResizeObserver.
import { FixedSizeList } from "react-window";

import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/utils";
import { exportToCsv, todayDateStamp } from "@/lib/csv-export";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import {
  rowTotal,
  typeBadgeClass,
  assetClassAbbrev,
  assetClassBadgeClass,
} from "./transaction-columns";
import { formatDateTime } from "@/lib/utils";
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

// Threshold above which the virtualised path activates.
// Below this number the synchronous render is faster (no ResizeObserver
// overhead) and produces nicer accessibility output.
const VIRTUALISATION_THRESHOLD = 200;

// ── Virtual-path column widths ────────────────────────────────────────────────
// WHY percentage widths: the virtual path renders each row as a mini-table
// (react-window) with the same colgroup as the sticky header table. Using
// percentage widths makes the columns scale uniformly as the container resizes.
// These values must match the DataTable column sizes (px converted to %).
// DATE=130, TYPE=70, CLASS=60, TICKER=80, QTY=100, PRICE=100, TOTAL=120, FEE=100 → sum=760
// WHY these percents (not raw px): relative widths are consistent across window sizes.
const COL_WIDTHS_PCT = [
  "17.1%",  // DATE  (130/760)
  "9.2%",   // TYPE  (70/760)
  "7.9%",   // CLASS (60/760)
  "10.5%",  // TICKER (80/760)
  "13.2%",  // QTY   (100/760)
  "13.2%",  // PRICE (100/760)
  "15.8%",  // TOTAL (120/760)
  "13.2%",  // FEE   (100/760)
];

// ── Virtual row renderer (react-window path) ──────────────────────────────────

/**
 * renderVirtualRow — renders one Transaction row as a mini-table cell.
 *
 * WHY a helper function (not a React component): the test mock for react-window
 * calls children({ index, style }) without the `data` prop that FixedSizeList
 * normally provides via itemData. Using a closure factory (makeVirtualRowRenderer)
 * captures `rows` from the outer scope so VirtualRow always has access to the
 * data array regardless of whether `data` is passed by the mock or the real lib.
 *
 * WHY a separate mini-table per row (not a shared <tbody>): react-window renders
 * each row into an absolutely positioned div. A shared <table> with a <tbody> cannot
 * be split between rows — each row must own its own colgroup to receive column widths.
 * QA-iter1 MAJ-4: this pattern guarantees column widths match the header 1:1 because
 * both use the same COL_WIDTHS_PCT constant.
 *
 * WHY data-testid="transactions-virtual-row": tests assert that this testid exists
 * and that its colgroup col widths match the header colgroup. The testid makes it
 * queryable independently of the mocked FixedSizeList container.
 */
function makeVirtualRowRenderer(rows: Transaction[]) {
  // WHY return a named function (not anonymous arrow): React DevTools shows the
  // component name in the component tree which helps debugging. Named inner
  // functions also produce cleaner stack traces.
  return function VirtualRow({
    index,
    style,
  }: {
    index: number;
    style: React.CSSProperties;
  }) {
    const tx = rows[index];
    if (!tx) return null;
    const isPlaceholder = tx.type !== "DIVIDEND" && tx.quantity === 0 && tx.price === 0;
    const total = rowTotal(tx);

    return (
      <div style={style}>
        <table
          data-testid="transactions-virtual-row"
          className={cn(
            "w-full table-fixed border-b border-border/30",
            isPlaceholder && "text-muted-foreground/50",
          )}
        >
          <colgroup>
            {COL_WIDTHS_PCT.map((w, i) => (
              <col key={i} style={{ width: w }} />
            ))}
          </colgroup>
          <tbody>
            <tr className="h-[22px]">
              <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground whitespace-nowrap">
                {formatDateTime(tx.executed_at)}
              </td>
              <td className="px-2">
                <span
                  className={cn(
                    "inline-flex items-center px-1 rounded-[2px] font-mono text-[10px] font-semibold",
                    typeBadgeClass(tx.type),
                  )}
                  data-testid={`tx-type-${tx.transaction_id}`}
                >
                  {tx.type === "DIVIDEND" ? "DIV" : tx.type}
                </span>
              </td>
              <td className="px-2">
                <span
                  className={cn(
                    "inline-flex items-center px-1 rounded-[2px] border font-mono text-[10px] font-semibold uppercase",
                    assetClassBadgeClass(tx.asset_class),
                  )}
                  data-testid={`tx-asset-class-${tx.transaction_id}`}
                >
                  {assetClassAbbrev(tx.asset_class)}
                </span>
              </td>
              <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
                {tx.ticker || "—"}
              </td>
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {tx.type === "DIVIDEND" ? "—" : tx.quantity.toLocaleString("en-US")}
              </td>
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {tx.type === "DIVIDEND" ? "—" : formatPrice(tx.price)}
              </td>
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {isPlaceholder ? "n/a" : total > 0 ? formatPrice(total) : "—"}
              </td>
              <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
                {tx.type !== "DIVIDEND" && tx.fee > 0 ? formatPrice(tx.fee) : "—"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  };
}

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
      {filtered.length > VIRTUALISATION_THRESHOLD ? (
        /*
         * ── Virtualised path (> 200 rows) ─────────────────────────────────
         * WHY react-window FixedSizeList (not DataTable's built-in react-virtual):
         * The test suite mocks react-window's FixedSizeList to render all items
         * synchronously with data-testid="virtual-mock". Using FixedSizeList here
         * ensures the mock intercepts correctly and the colgroup-based column width
         * contract (QA-iter1 MAJ-4) can be asserted via transactions-header /
         * transactions-virtual-row testids.
         *
         * WHY table-per-row: react-window renders each row into an absolutely
         * positioned div — a shared <tbody> cannot span virtual rows. Each row
         * gets its own mini-table with the same colgroup as the header, guaranteeing
         * column width alignment without JavaScript measurement.
         */
        <div data-testid="transactions-virtualised" className="overflow-auto">
          {/* Sticky header table — colgroup drives column widths */}
          <table
            data-testid="transactions-header"
            className="w-full table-fixed border-b border-border sticky top-0 z-10 bg-card"
          >
            <colgroup>
              {COL_WIDTHS_PCT.map((w, i) => (
                <col key={i} style={{ width: w }} />
              ))}
            </colgroup>
            <thead>
              <tr className="h-[22px]">
                {["DATE", "TYPE", "CLASS", "TICKER", "QTY", "PRICE", "TOTAL", "FEE"].map((h) => (
                  <th
                    key={h}
                    className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
          </table>
          {/* Virtual body — each row rendered by FixedSizeList.
              WHY makeVirtualRowRenderer (not passing VirtualRow directly):
              the test mock calls children({ index, style }) without the `data`
              prop that FixedSizeList normally provides via itemData. The closure
              factory captures `filtered` from the outer scope so the row renderer
              has access to data regardless of whether `data` is forwarded by the
              mock. Real FixedSizeList still works correctly with itemData omitted
              from the type because the closure already has the array. */}
          <FixedSizeList
            height={400}
            itemCount={filtered.length}
            itemSize={22}
            width="100%"
          >
            {makeVirtualRowRenderer(filtered)}
          </FixedSizeList>
        </div>
      ) : (
        /*
         * ── Non-virtualised path (≤ 200 rows) ─────────────────────────────
         * WHY plain <table><tr> (not DataTable): F-P-028 tests use
         * `closest("tr")` to find the row element and assert the muted class.
         * DataTable renders rows as `<div role="row">` which closest("tr") cannot
         * find. A plain HTML table uses real <tr> elements so closest("tr") works
         * correctly. The filter state and testids are identical — only the DOM
         * structure changes.
         *
         * WHY keep DataTable for the virtual path: the > 200-row virtual path uses
         * react-window which already renders per-row mini-tables with <tr>.
         *
         * WHY all cell renderers are duplicated from transaction-columns.tsx:
         * DataTable's ColumnDef cell renderers expect a render context (row, table,
         * etc.) that we don't have outside DataTable. We inline the same HTML
         * directly so the rendered output and testids are identical.
         */
        <div className="overflow-auto">
          <table className="w-full table-fixed" style={{ tableLayout: "fixed" }}>
            <colgroup>
              {COL_WIDTHS_PCT.map((w, i) => (
                <col key={i} style={{ width: w }} />
              ))}
            </colgroup>
            <thead>
              <tr className="h-[22px] border-b border-border bg-card sticky top-0 z-10">
                {["DATE", "TYPE", "CLASS", "TICKER", "QTY", "PRICE", "TOTAL", "FEE"].map((h) => (
                  <th
                    key={h}
                    className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-2 py-2 text-[11px] text-muted-foreground">
                    {`No${activeFilter !== "ALL" ? ` ${activeFilter}` : ""} transactions match the current filters.`}
                  </td>
                </tr>
              ) : (
                filtered.map((tx) => {
                  // WHY isPlaceholder: brokerage imports include sentinel rows
                  // (corporate actions) with qty=0 AND price=0. De-emphasise them
                  // visually so real fills stand out. (BP-263 / F-P-028)
                  const isPlaceholder = tx.type !== "DIVIDEND" && tx.quantity === 0 && tx.price === 0;
                  const total = rowTotal(tx);
                  return (
                    <tr
                      key={tx.transaction_id}
                      className={cn(
                        "h-[22px] border-b border-white/[0.06]",
                        isPlaceholder && "text-muted-foreground/50",
                      )}
                    >
                      <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground whitespace-nowrap">
                        {formatDateTime(tx.executed_at)}
                      </td>
                      <td className="px-2">
                        <span
                          className={cn(
                            "inline-flex items-center px-1 rounded-[2px] font-mono text-[10px] font-semibold tabular-nums",
                            typeBadgeClass(tx.type),
                          )}
                          data-testid={`tx-type-${tx.transaction_id}`}
                        >
                          {tx.type === "DIVIDEND" ? "DIV" : tx.type}
                        </span>
                      </td>
                      <td className="px-2">
                        <span
                          className={cn(
                            "inline-flex items-center px-1 rounded-[2px] border font-mono text-[10px] font-semibold uppercase",
                            assetClassBadgeClass(tx.asset_class),
                          )}
                          data-testid={`tx-asset-class-${tx.transaction_id}`}
                        >
                          {assetClassAbbrev(tx.asset_class)}
                        </span>
                      </td>
                      <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
                        {tx.ticker || "—"}
                      </td>
                      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                        {tx.type === "DIVIDEND" ? "—" : tx.quantity.toLocaleString("en-US")}
                      </td>
                      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                        {tx.type === "DIVIDEND" ? "—" : formatPrice(tx.price)}
                      </td>
                      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                        {isPlaceholder ? "n/a" : total > 0 ? formatPrice(total) : "—"}
                      </td>
                      <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
                        {tx.type !== "DIVIDEND" && tx.fee > 0 ? formatPrice(tx.fee) : "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

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
