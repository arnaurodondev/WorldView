/**
 * components/portfolio/TransactionsTable.tsx — Transaction history with rich filter bar
 *
 * WHY THIS EXISTS: Traders need to review their execution history to verify fills,
 * assess average-cost basis accuracy, and track dividend income. Extracted from
 * portfolio/page.tsx as a standalone component so it can be tested independently.
 *
 * WHY 7 COLUMNS: Date | Type | Ticker | Qty | Price | Total | Fee covers the
 * full picture of a trade execution without becoming wider than a typical panel.
 *
 * WHY DIVIDEND row shows "—" for Qty and Price: a dividend is an income event,
 * not a share purchase/sale. Qty and Price are meaningless for dividends; the
 * relevant amount is in the Fee column (repurposed as "amount" for DIVIDEND type).
 *
 * PLAN-0051 Wave A enhancements (T-A-1-01 / T-A-1-02 / T-A-1-03):
 *   • Date-range picker (From / To) — calendar-bounded filter
 *   • Ticker autocomplete (datalist of currently-loaded tickers)
 *   • Currency filter (USD / EUR / All) — replaces a "market" filter the
 *     gateway can't express today (no `market`/`exchange` field on Transaction;
 *     see TODO below)
 *   • Min / Max amount sliders (number inputs)
 *   • Free-text search (debounced 200 ms, matches ticker / type / notes)
 *   • Clear-filters button (only shown when at least one filter is active)
 *   • CSV export (papaparse) — `transactions-YYYY-MM-DD.csv`
 *   • Virtualisation via react-window FixedSizeList when filtered.length > 200
 *   • Totals row (BUY cost / SELL proceeds / DIV income), updates with filters
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Transactions tab
 * DATA SOURCE: getTransactions() via parent page
 * DESIGN REFERENCE: PRD-0031 §8.4 Transactions Table; PLAN-0051 Wave A
 */

"use client";
// WHY "use client": every interactive piece in this file requires browser-only
// behaviour: useState (filter state), useMemo, useEffect (debounce timer),
// react-window (uses ResizeObserver / DOM measurements), HTML <input type=date>
// rendering, and synchronous DOM document.createElement for the CSV download.
// None of this can run during server rendering.

import { useEffect, useMemo, useState } from "react";
import { FixedSizeList, type ListChildComponentProps } from "react-window";

import { cn } from "@/lib/utils";
import { formatPrice, formatDateTime } from "@/lib/utils";
import { exportToCsv, todayDateStamp } from "@/lib/csv-export";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { Transaction } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TransactionsTableProps {
  transactions: Transaction[];
  /**
   * @deprecated F-205 (QA iter-2): the gateway / S1 now populate ``ticker``
   * directly on every transaction (``ListTransactionsUseCase`` joins to
   * ``instruments``). The fallback lookup is retained ONLY so existing call
   * sites that still pass the map don't break — it's no longer required for
   * a correct render. New consumers MUST omit this prop.
   *
   * Historical context: BP-262 added this workaround when ``tx.ticker`` was
   * always empty. The server-side enrichment supersedes it.
   */
  tickerByInstrumentId?: Record<string, string | null | undefined>;
}

// WHY "ALL" exists as a literal value: avoids special-casing null in filter
// logic. Every tx.type matches "ALL"; BUY matches only BUY transactions, etc.
type FilterType = "ALL" | "BUY" | "SELL" | "DIVIDEND";

// WHY a discriminated currency literal "ALL" exists for the same reason:
// the filter compares tx.currency to the value; "ALL" short-circuits the
// comparison rather than threading a nullable around.
type CurrencyFilter = "ALL" | "USD" | "EUR";

// Threshold above which we render rows through react-window. Below this
// number, the synchronous <tbody> path is faster (no ResizeObserver, no
// extra wrapping divs) and produces nicer accessibility output.
const VIRTUALISATION_THRESHOLD = 200;

// Row height in pixels — must match the <tr h-[22px]> below or virtualised
// rows visually disagree with the unvirtualised ones during dev.
const ROW_PX = 22;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * typeBadgeClass — color for the type badge based on transaction type.
 *
 * WHY background + text pair: a colored badge is more scannable than plain text.
 * Bloomberg uses color-coded action indicators in trade blotters for the same reason.
 */
function typeBadgeClass(type: Transaction["type"]): string {
  switch (type) {
    case "BUY":
      return "bg-positive/20 text-positive";
    case "SELL":
      return "bg-negative/20 text-negative";
    case "DIVIDEND":
      // WHY text-primary for DIVIDEND: it's a neutral income event (neither gain nor loss).
      // text-primary (sky blue) signals "informational" without positive/negative connotation.
      return "bg-primary/20 text-primary";
    default:
      return "text-muted-foreground";
  }
}

/**
 * Compute "total" the way every consumer of this table expects it:
 *   BUY/SELL → quantity × price (gross of fees)
 *   DIVIDEND → tx.amount (broker-reported cash payment), 0 fallback
 *
 * Centralised here because both the on-screen Total cell, the Min/Max amount
 * filter, and the totals row all need the same definition. Drift would
 * silently mis-filter rows.
 */
function rowTotal(tx: Transaction): number {
  if (tx.type === "DIVIDEND") return tx.amount ?? 0;
  return tx.quantity * tx.price;
}

/**
 * Inline debounce — returns a value that lags the input by `delayMs`.
 *
 * WHY local (not the shared hooks/useDebounce.ts): this file is intentionally
 * dependency-light. The shared hook does the same thing but importing it would
 * also pull the hook's file-level header noise into this module. The inline
 * version is 8 lines and entirely self-explanatory.
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

// WHY a shared className constant (not inline strings everywhere): we want
// every input in the filter bar — date, text, number, datalist trigger — to
// share the exact same height, padding, font, border, and focus colour. A
// constant keeps the design tokens centralised and prevents drift when we
// later add another input.
//
// WHY h-6 (24 px): the filter bar is 36 px tall (h-9), and 24 px inputs
// leave 6 px breathing room top + bottom — same proportion as the existing
// segmented filter buttons. WHY rounded-[2px]: terminal-grade chrome (no
// rounded "card" look), matches design system. WHY bg-card: makes the input
// distinguishable from the bg-card filter row by virtue of the border alone.
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
  // Each filter is its own piece of state so we can clear them independently
  // and so React's reconciliation doesn't re-render the whole row body when
  // an unrelated filter changes (state-co-location keeps render scopes tight).
  const [activeFilter, setActiveFilter] = useState<FilterType>("ALL");
  const [fromDate, setFromDate] = useState<string>(""); // YYYY-MM-DD or ""
  const [toDate, setToDate] = useState<string>("");
  const [tickerFilter, setTickerFilter] = useState<string>("");
  const [currencyFilter, setCurrencyFilter] = useState<CurrencyFilter>("ALL");
  const [minAmount, setMinAmount] = useState<string>(""); // string so blank ≠ 0
  const [maxAmount, setMaxAmount] = useState<string>("");
  const [searchRaw, setSearchRaw] = useState<string>("");

  // Debounce free-text search so we don't recompute the filtered list on
  // every keystroke. 200 ms feels instantaneous on a fast typist while
  // collapsing the worst-case 10-keystroke burst into one pass.
  const search = useDebouncedValue(searchRaw, 200);

  // TODO(PLAN-0051 / backend): the original spec calls for a "market" filter
  // (NYSE / NASDAQ / LSE / etc). The Transaction shape returned by S9 today
  // exposes no market/exchange/MIC field; only `currency`. A future S1
  // enhancement should surface `instrument.exchange_mic` on the transaction
  // payload — until then we degrade gracefully to a currency filter, which
  // is a reasonable proxy for region (USD ≈ US, EUR ≈ EU).

  // ── Filter active? ────────────────────────────────────────────────────────
  // Used to toggle the "Clear filters" button visibility. Combine all filter
  // pieces into one boolean so we don't litter JSX with eight conditions.
  const anyFilterActive =
    activeFilter !== "ALL" ||
    fromDate !== "" ||
    toDate !== "" ||
    tickerFilter.trim() !== "" ||
    currencyFilter !== "ALL" ||
    minAmount !== "" ||
    maxAmount !== "" ||
    searchRaw !== "";

  /** Reset every filter to its initial empty/ALL state. */
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

  // ── Pre-compute the unique ticker datalist ────────────────────────────────
  // WHY useMemo: this runs once per transactions change rather than on every
  // keystroke / filter tweak. The set deduplicates while we walk the array
  // once; sorting once on the way out gives users a predictable autocomplete.
  const tickerOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const tx of transactions) {
      const t = tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || "";
      if (t) seen.add(t);
    }
    return Array.from(seen).sort();
  }, [transactions, tickerByInstrumentId]);

  // ── Empty state guard ─────────────────────────────────────────────────────
  // F-P-016 (PLAN-0051 W6): empty-state copy guide — Title + Body explanation.
  // - Title (short, descriptive): "No transactions yet."
  // - Body (WHY the user might see this): "Connect a brokerage to import
  //   activity, or use Add Position to record a trade manually."
  // The single-line InlineEmptyState renders the combined sentence so the
  // user understands their next step rather than just learning that the
  // table is empty.
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

  // Parse min/max once outside the filter loop — turning "" into NaN here lets
  // us short-circuit cheaply per row with `Number.isNaN` rather than re-running
  // parseFloat for every single transaction.
  const minAmt = minAmount === "" ? NaN : Number(minAmount);
  const maxAmt = maxAmount === "" ? NaN : Number(maxAmount);
  const tickerLower = tickerFilter.trim().toLowerCase();
  const searchLower = search.trim().toLowerCase();

  const filtered = sorted.filter((tx) => {
    // Type segmented filter
    if (activeFilter !== "ALL" && tx.type !== activeFilter) return false;

    // Date range — string comparison is correct because executed_at is ISO
    // 8601 with a YYYY-... prefix and our pickers emit YYYY-MM-DD.
    // WHY string comparison (not Date parse): avoids timezone shifts that
    // would otherwise drop a tx executed at 00:30 UTC out of "today's" range
    // when the user is in PST.
    if (fromDate && tx.executed_at.slice(0, 10) < fromDate) return false;
    if (toDate && tx.executed_at.slice(0, 10) > toDate) return false;

    // Ticker substring (case-insensitive). Look up enriched ticker first so
    // the filter respects the same value the user sees in the table.
    if (tickerLower) {
      const t = (
        tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || ""
      ).toLowerCase();
      if (!t.includes(tickerLower)) return false;
    }

    // Currency filter
    if (currencyFilter !== "ALL" && tx.currency !== currencyFilter) {
      return false;
    }

    // Amount range — applies to the row's "total" (qty*price for BUY/SELL,
    // amount for DIVIDEND) so the filter behaves the way the user reads the
    // Total column. NaN guards skip the bound when the user left it blank.
    const total = rowTotal(tx);
    if (!Number.isNaN(minAmt) && total < minAmt) return false;
    if (!Number.isNaN(maxAmt) && total > maxAmt) return false;

    // Free-text search — matches against ticker, type, and notes (the only
    // textual fields). We pre-lowercased the term once outside the loop.
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
  // WHY recompute on every render (no useMemo): the sums are a single linear
  // pass over `filtered`, which is itself recomputed each render. The memo
  // would also depend on `filtered`, making it churn anyway — it's strictly
  // wasted bookkeeping. Keep it explicit.
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

  // ── CSV export handler ────────────────────────────────────────────────────
  // WHY captured by a function (not inlined onClick): unit tests can mock
  // `exportToCsv` and assert the helper was called with the filtered rows.
  // Inlining would force tests to spy on the global Blob API instead.
  function handleExportCsv() {
    exportToCsv<Transaction>({
      filenameStem: `transactions-${todayDateStamp()}`,
      rows: filtered,
      columns: [
        // WHY ISO-8601 for Date: spreadsheet "Date" import preserves sort order.
        // The on-screen format is human-friendly (formatDateTime), but for export
        // we want machine-friendly so an accountant can run formulas on it.
        { header: "Date", accessor: (r) => r.executed_at },
        { header: "Type", accessor: (r) => r.type },
        {
          header: "Ticker",
          accessor: (r) =>
            r.ticker || tickerByInstrumentId?.[r.instrument_id] || "",
        },
        // WHY emit numbers (not formatted strings) for Qty/Price/Total/Fee:
        // formatPrice would lose precision and turn $1,234.50 into a string
        // Excel can't sum without a manual "convert text to number" step.
        { header: "Quantity", accessor: (r) => r.quantity },
        { header: "Price", accessor: (r) => r.price },
        { header: "Total", accessor: (r) => rowTotal(r) },
        { header: "Fee", accessor: (r) => r.fee },
        { header: "Currency", accessor: (r) => r.currency },
      ],
    });
  }

  // ── Render: row presenter ─────────────────────────────────────────────────
  // Extracted so both the unvirtualised <tbody> path and the react-window
  // path render an identical DOM shape. WHY a function (not a component): we
  // need the FixedSizeList "Row" prop to receive `index` + `style`, and the
  // child must spread style into the outer element. Creating a component would
  // mean re-shaping props for the unvirtualised path; a function with the same
  // signature in both paths is the simplest unification.
  function renderTxRow(tx: Transaction, style?: React.CSSProperties) {
    const isDividend = tx.type === "DIVIDEND";
    // WHY this branch:
    //   * BUY / SELL → total = quantity * price (cost / proceeds before fees)
    //   * DIVIDEND   → quantity≈0 and price≈0; the cash payment lives in
    //                  `tx.amount` (PLAN-0046 / BP-263).
    const total = isDividend ? (tx.amount ?? 0) : tx.quantity * tx.price;
    // WHY enrichment lookup: tx.ticker is empty from the gateway because
    // S1's TransactionListItem omits ticker. The parent page loads holding
    // overviews keyed by instrument_id and passes them here as a lookup.
    const enrichedTicker =
      tx.ticker || tickerByInstrumentId?.[tx.instrument_id] || "";
    // WHY zero-qty/zero-price guard (B-6): brokerage imports occasionally
    // include sentinel rows (corporate actions, fee-only adjustments) with
    // qty=0 AND price=0. These are not user-actionable trades — render the
    // row in a muted style so it visually de-emphasises against real fills.
    const isPlaceholder = !isDividend && tx.quantity === 0 && tx.price === 0;

    return (
      <tr
        key={tx.transaction_id}
        // The `style` is only set when react-window is positioning the row
        // absolutely (`top: NNNpx`); the unvirtualised path passes undefined.
        style={style}
        className={cn(
          "h-[22px] hover:bg-muted/40 transition-colors",
          isPlaceholder && "text-muted-foreground/50",
        )}
      >
        {/* Date */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground whitespace-nowrap">
          {formatDateTime(tx.executed_at)}
        </td>

        {/* Type badge — data-testid for testing BUY/SELL color classes */}
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

        {/* Ticker */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
          {enrichedTicker || "—"}
        </td>

        {/* Qty — "—" for DIVIDEND (not applicable) */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
          {isDividend ? "—" : tx.quantity.toLocaleString("en-US")}
        </td>

        {/* Price — "—" for DIVIDEND */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
          {isDividend ? "—" : formatPrice(tx.price)}
        </td>

        {/* Total */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
          {isPlaceholder ? "n/a" : total > 0 ? formatPrice(total) : "—"}
        </td>

        {/* Fee */}
        <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
          {!isDividend && tx.fee > 0 ? formatPrice(tx.fee) : "—"}
        </td>
      </tr>
    );
  }

  // The react-window child component MUST return a single positioned element.
  // WHY a <table> wrapper inside the row: react-window applies `top: Npx;
  // position: absolute;` to the rendered child. Wrapping in a single-row
  // <table> preserves <td> layout / alignment with the header. Without the
  // wrapper, a bare <tr> would render with default block layout and lose
  // column alignment.
  const VirtualRow = ({ index, style }: ListChildComponentProps) => {
    const tx = filtered[index];
    return (
      <table
        // WHY width:100% inside style: the parent <FixedSizeList> sets a
        // fixed pixel width based on its container. We want each row to span
        // that full width so columns align with the header table.
        style={{ ...style, width: "100%" }}
        className="border-collapse text-[11px] table-fixed"
      >
        <colgroup>
          {/* Same column widths as the static header — width:auto everywhere
              except the right-aligned numerics which we let the renderer size
              naturally; in practice the header table establishes the widths
              and these row tables match because table-fixed inherits them
              proportionally. We rely on the wrapping div's width to be
              identical to the header div. */}
        </colgroup>
        <tbody>{renderTxRow(tx, undefined)}</tbody>
      </table>
    );
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-0">
      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      {/* WHY h-9: matches the standard 36 px header bar height used throughout.
          WHY flex-wrap + gap-y: with eight inputs we will overflow on narrow
          panel widths; wrapping is the least-bad fallback. The minimum the
          user will ever see at a normal desktop width is one row. */}
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

        {/* Date range — From / To. WHY label="From" / "To": <input type=date>
            doesn't carry an implicit label; some screen readers announce only
            "date picker", so we wrap with a visually-tiny but a11y-visible
            label. */}
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

        {/* Ticker autocomplete (datalist). WHY datalist (not a custom Combobox):
            datalist is native, accessible by default, supports keyboard nav,
            and adds zero JS bytes. The downside is limited styling — the
            dropdown appearance is browser-controlled. Acceptable for v1. */}
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

        {/* Currency filter — degrades gracefully from "market" filter. */}
        <select
          aria-label="Filter by currency"
          className={cn(INPUT_CLS, "w-16 cursor-pointer")}
          value={currencyFilter}
          onChange={(e) =>
            setCurrencyFilter(e.target.value as CurrencyFilter)
          }
        >
          <option value="ALL">All</option>
          <option value="USD">USD</option>
          <option value="EUR">EUR</option>
        </select>

        {/* Min / Max amount. WHY type=number: gives mobile users a numeric
            keypad and prevents non-numeric input. inputMode=decimal is also
            set for legacy browsers that ignore `type=number` styling. */}
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

        {/* Search — debounced internally. */}
        <input
          type="search"
          aria-label="Search transactions"
          placeholder="Search…"
          className={cn(INPUT_CLS, "w-32")}
          value={searchRaw}
          onChange={(e) => setSearchRaw(e.target.value)}
        />

        {/* Clear filters — only visible when something is filtered. WHY
            ml-auto on the LAST visible item we want at the right edge: it
            forces the spacer between the last input and this trailing pill,
            even with flex-wrap. */}
        {anyFilterActive && (
          <button
            type="button"
            onClick={clearFilters}
            className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground transition-colors"
          >
            Clear filters
          </button>
        )}

        {/* CSV export. WHY a stand-alone button (not a dropdown): we only
            offer one format today. PLAN-0051 T-B-2-07 introduces the
            screener-side dropdown for CSV/XLSX/PDF. */}
        <button
          type="button"
          aria-label="Export transactions as CSV"
          onClick={handleExportCsv}
          className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground transition-colors"
        >
          Export CSV
        </button>

        {/* Row count — shows how many transactions match the active filters */}
        <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
          {filtered.length} / {transactions.length}
        </span>
      </div>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <div className="overflow-auto">
        <table className="w-full border-collapse text-[11px]">
          <thead className="sticky top-0 bg-card z-10">
            <tr className="h-[22px] border-b border-border">
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                DATE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                TYPE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                TICKER
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                QTY
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                PRICE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                TOTAL
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                FEE
              </th>
            </tr>
          </thead>

          {/* WHY split rendering paths:
                small table (≤ 200 rows) → static <tbody> for accessibility +
                    sticky-header behaviour. react-window adds a virtual
                    scroller div which would clip the sticky header.
                large table (> 200 rows) → react-window for perf. */}
          {filtered.length === 0 ? (
            <tbody className="divide-y divide-border/30">
              <tr>
                <td
                  colSpan={7}
                  className="px-2 py-3 text-center text-[11px] text-muted-foreground"
                >
                  No {activeFilter === "ALL" ? "" : activeFilter} transactions match
                  the current filters.
                </td>
              </tr>
            </tbody>
          ) : filtered.length > VIRTUALISATION_THRESHOLD ? (
            // Render the virtualisation container in a NON-table context:
            // FixedSizeList wraps each row in <div style="position:absolute;
            // top: …">, which is invalid as a direct child of <tbody>. We
            // close the static table here and open a fresh containing div
            // immediately below; the rows are mini-tables that share column
            // widths via the table-fixed class on the row.
            //
            // WHY accept this DOM compromise: virtualised tables are a known
            // hard problem in the React ecosystem. The alternative is
            // CSS Grid which loses native row hit-testing; the mini-table
            // approach keeps tables semantic on a per-row basis.
            <tbody />
          ) : (
            <tbody className="divide-y divide-border/30">
              {filtered.map((tx) => renderTxRow(tx))}
            </tbody>
          )}
        </table>

        {/* Virtualised body — only when over threshold AND not empty. */}
        {filtered.length > VIRTUALISATION_THRESHOLD && (
          <div data-testid="transactions-virtualised">
            <FixedSizeList
              height={ROW_PX * Math.min(filtered.length, 20)}
              itemCount={filtered.length}
              itemSize={ROW_PX}
              width="100%"
            >
              {VirtualRow}
            </FixedSizeList>
          </div>
        )}
      </div>

      {/* ── Totals row ──────────────────────────────────────────────────── */}
      {/* WHY render outside the table: see the tbody/FixedSizeList comment
          above — keeping totals as its own div sidesteps the virtualisation
          DOM constraints AND gives us a pinned strip across both rendering
          paths. WHY border-t-2: emphasises a summary row visually different
          from the regular border-t between scroll rows. */}
      <div
        data-testid="transactions-totals"
        className="flex h-7 items-center gap-4 border-t-2 border-border bg-card px-2 shrink-0"
      >
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Totals
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          BUY cost{" "}
          <span
            data-testid="totals-buy"
            className="ml-1 text-foreground"
          >
            {formatPrice(buyCost)}
          </span>
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          SELL proceeds{" "}
          <span
            data-testid="totals-sell"
            className="ml-1 text-foreground"
          >
            {formatPrice(sellProceeds)}
          </span>
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          DIV income{" "}
          <span
            data-testid="totals-div"
            className="ml-1 text-foreground"
          >
            {formatPrice(divIncome)}
          </span>
        </span>
      </div>
    </div>
  );
}
