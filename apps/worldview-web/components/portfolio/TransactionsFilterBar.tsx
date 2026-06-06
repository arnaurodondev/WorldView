/**
 * components/portfolio/TransactionsFilterBar.tsx — Compact one-row filter bar
 * for the Transactions tab (PRD-0089 SA-C Task 4).
 *
 * WHY ONE ROW: the transactions table already has the filter bar in-component,
 * but PRD-0089 SA-C specifies a dedicated, controlled filter bar that receives
 * its state from the parent (TransactionsTab) via URL-synced nuqs state.
 * Keeping the filter bar as a pure controlled component (no local state) makes
 * it trivially testable and reusable if the transactions table is embedded in
 * other pages (e.g., instrument detail Transactions tab).
 *
 * PILL BUTTONS: Type filter uses pill buttons (not a <select>) because there
 * are only 6 options and tapping a pill is faster on touch screens than opening
 * a dropdown. The active pill highlights with bg-primary to make selection
 * immediately obvious.
 *
 * CSV EXPORT: passes `filteredItems` through a simple header+row loop and uses
 * window.URL.createObjectURL to trigger a browser download without any server
 * round-trip. The CSV is generated client-side from the current filtered rows.
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 * DATA SOURCE: props (controlled component — no internal state)
 */

"use client";
// WHY "use client": onClick handlers, DOM manipulation for CSV download.

import { cn } from "@/lib/utils";
import type { TransactionFilters } from "@/features/portfolio/hooks/useTransactionsFilterState";
import type { Transaction } from "@/types/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface TransactionsFilterBarProps {
  /** Current filter values — controlled from parent via URL state */
  value: TransactionFilters;
  /** Called whenever any filter field changes */
  onChange: (f: TransactionFilters) => void;
  /** All ticker symbols present in the full (unfiltered) transaction list */
  tickerOptions: string[];
  /** Total transaction count (unfiltered) */
  totalCount: number;
  /** Currently visible transaction count (after filters applied) */
  filteredCount: number;
  /**
   * The filtered transaction rows — needed to generate the CSV.
   * WHY a separate prop: the filter bar doesn't own the filtering logic; the
   * parent applies filters and passes the result here. This keeps the bar
   * free of filtering code and independently testable.
   */
  filteredItems: Transaction[];
}

// ── Constants ──────────────────────────────────────────────────────────────────

// Type pill options. "All" means no filter. The others match the Transaction.type
// enum values used by the parent filter logic, except "DIV" which maps to
// "DIVIDEND" in the data model. The parent TransactionsTab handles the mapping.
const TYPE_OPTIONS = ["All", "BUY", "SELL", "DIV", "SPLIT", "TRSF"] as const;
type TypeOption = (typeof TYPE_OPTIONS)[number];

// Shared input class — height, padding, font, border, focus ring.
// WHY h-6: 24px is the standard control height in this design system (matches
// the type-filter pill height and the action buttons).
const INPUT_CLS =
  "h-6 px-2 text-[11px] font-mono bg-card border border-border rounded-[2px] " +
  "text-foreground placeholder:text-muted-foreground focus-visible:outline-none " +
  "focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-ring";

// ── CSV helpers ────────────────────────────────────────────────────────────────

/**
 * buildCsvContent — turn a Transaction array into a CSV string.
 *
 * WHY not a shared utility: this bar is the only place that needs transaction CSV
 * export. The existing exportToCsv utility from lib/csv-export.ts is fine for
 * complex cases; here we inline a simple loop so the bar has no extra imports.
 *
 * FIELDS: Date, Type, Ticker, Qty, Price, Total, Fee, Currency, Notes
 * WHY not all fields: transaction_id and portfolio_id are internal UUIDs with
 * no value to the end user reviewing exported data.
 */
function buildCsvContent(rows: Transaction[]): string {
  // Header row
  const headers = [
    "Date",
    "Type",
    "Ticker",
    "Asset Class",
    "Qty",
    "Price",
    "Total",
    "Fee",
    "Currency",
    "Notes",
  ];

  // Data rows — each cell stringified and quoted if it contains a comma.
  const dataRows = rows.map((tx) => {
    const total =
      tx.type === "DIVIDEND"
        ? (tx.amount ?? 0)
        : tx.quantity * tx.price;

    // WHY quote(v): values that contain commas (like notes) would break CSV
    // parsers if not wrapped in double quotes.
    function quote(v: string | number | null | undefined): string {
      const s = String(v ?? "");
      // RFC 4180: if value contains comma, double-quote, or newline → wrap in quotes
      if (s.includes(",") || s.includes('"') || s.includes("\n")) {
        return `"${s.replace(/"/g, '""')}"`;
      }
      return s;
    }

    return [
      quote(tx.executed_at),
      quote(tx.type),
      quote(tx.ticker),
      quote(tx.asset_class),
      quote(tx.quantity),
      quote(tx.price),
      quote(total),
      quote(tx.fee),
      quote(tx.currency),
      quote(tx.notes),
    ].join(",");
  });

  return [headers.join(","), ...dataRows].join("\r\n");
}

/**
 * triggerCsvDownload — create a Blob + object URL and programmatically click
 * a hidden <a> to download the CSV.
 *
 * WHY window.URL.createObjectURL: avoids a server round-trip. The CSV is
 * generated entirely in the browser from the already-loaded filtered data.
 * The object URL is revoked after the click to avoid memory leaks.
 */
function triggerCsvDownload(csv: string, filename: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke the object URL after a short delay so the browser completes the
  // download before the URL becomes invalid.
  setTimeout(() => window.URL.revokeObjectURL(url), 100);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TransactionsFilterBar({
  value,
  onChange,
  tickerOptions,
  totalCount,
  filteredCount,
  filteredItems,
}: TransactionsFilterBarProps) {
  // ── Helper to update a single field without touching others ────────────
  // WHY this helper: every filter control calls onChange with the full filter
  // object, not just the changed field. Rather than repeating `{ ...value, X: newVal }`
  // in every handler, we centralise it here.
  function patch(partial: Partial<TransactionFilters>) {
    onChange({ ...value, ...partial });
  }

  // ── CSV export handler ─────────────────────────────────────────────────
  function handleExportCsv() {
    const csv = buildCsvContent(filteredItems);
    // Filename includes today's date so exports from different days don't
    // overwrite each other in the Downloads folder.
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    triggerCsvDownload(csv, `transactions-${today}.csv`);
  }

  // ── Check if any filter is active ─────────────────────────────────────
  // WHY: show the Reset button only when at least one filter diverges from
  // the default. This prevents visual clutter when no filter is active.
  const anyActive =
    value.type !== "All" ||
    value.dateFrom !== "" ||
    value.dateTo !== "" ||
    value.ticker !== "" ||
    value.minAmount !== "" ||
    value.maxAmount !== "" ||
    value.currency !== "" ||
    value.search !== "";

  // ── Render ────────────────────────────────────────────────────────────
  return (
    // WHY flex-wrap: on narrow viewports (< xl) the controls wrap to a second
    // line rather than overflowing or clipping. On wide viewports everything
    // fits in ~32px height.
    <div
      data-testid="transactions-filter-bar"
      className="flex flex-wrap items-center gap-1 gap-y-1 border-b border-border px-2 py-1 shrink-0"
    >
      {/* ── Type pill buttons ────────────────────────────────── */}
      {/* WHY pills not a dropdown: 6 options, each 2-4 chars wide. Tapping
          a pill is faster than opening a dropdown, and the active pill is
          visible at a glance without opening anything. */}
      <div className="flex items-center gap-0.5" role="group" aria-label="Filter by transaction type">
        {TYPE_OPTIONS.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={value.type === t}
            aria-label={`Show ${t === "All" ? "all transactions" : t + " transactions"}`}
            onClick={() => patch({ type: t as TypeOption })}
            className={cn(
              "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
              // WHY separate active/inactive styles: active pill must stand out
              // against the dark background at a glance. bg-primary/10 + border-primary
              // achieves that without overpowering the content below.
              value.type === t
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-muted text-muted-foreground border-border hover:text-foreground",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Date from ─────────────────────────────────────────── */}
      <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
        From
        <input
          type="date"
          aria-label="Filter from date"
          // WHY w-[100px]: wide enough for YYYY-MM-DD with the browser's date
          // input chrome on most platforms.
          className={cn(INPUT_CLS, "w-[100px]")}
          value={value.dateFrom}
          onChange={(e) => patch({ dateFrom: e.target.value })}
        />
      </label>

      {/* ── Date to ───────────────────────────────────────────── */}
      <label className="flex items-center gap-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
        To
        <input
          type="date"
          aria-label="Filter to date"
          className={cn(INPUT_CLS, "w-[100px]")}
          value={value.dateTo}
          onChange={(e) => patch({ dateTo: e.target.value })}
        />
      </label>

      {/* ── Ticker search ─────────────────────────────────────── */}
      <input
        type="text"
        aria-label="Filter by ticker"
        placeholder="Ticker…"
        list="filter-bar-ticker-list"
        className={cn(INPUT_CLS, "w-20")}
        value={value.ticker}
        onChange={(e) => patch({ ticker: e.target.value })}
      />
      {/* WHY datalist: provides auto-complete suggestions from the actual
          tickers in the dataset without requiring a custom dropdown. */}
      <datalist id="filter-bar-ticker-list">
        {tickerOptions.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>

      {/* ── Currency select ───────────────────────────────────── */}
      <select
        aria-label="Filter by currency"
        // WHY w-[60px]: "Any" and 3-char currency codes fit within 60px.
        className={cn(INPUT_CLS, "w-[60px] cursor-pointer")}
        value={value.currency}
        onChange={(e) => patch({ currency: e.target.value })}
      >
        <option value="">Any</option>
        <option value="USD">USD</option>
        <option value="CAD">CAD</option>
        <option value="EUR">EUR</option>
        <option value="GBP">GBP</option>
      </select>

      {/* ── Count display ─────────────────────────────────────── */}
      {/* WHY ml-auto: pushes the count + action buttons to the right edge
          of the bar, matching Bloomberg-style filter bars where the count
          and actions are on the trailing side. */}
      <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
        {filteredCount} / {totalCount}
      </span>

      {/* ── Reset button — shown only when filters are active ─── */}
      {anyActive && (
        <button
          type="button"
          onClick={() =>
            onChange({
              type: "All",
              dateFrom: "",
              dateTo: "",
              ticker: "",
              minAmount: "",
              maxAmount: "",
              currency: "",
              search: "",
            })
          }
          aria-label="Reset all transaction filters"
          className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground hover:text-foreground hover:border-foreground transition-colors"
        >
          Reset
        </button>
      )}

      {/* ── Export CSV ────────────────────────────────────────── */}
      <button
        type="button"
        aria-label="Export filtered transactions as CSV"
        onClick={handleExportCsv}
        disabled={filteredItems.length === 0}
        // WHY disabled when empty: exporting a 0-row CSV is confusing — the
        // file would contain only headers, which looks like a bug to the user.
        className={cn(
          "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
          filteredItems.length === 0
            ? "border-border text-muted-foreground/40 cursor-not-allowed"
            : "border-border text-muted-foreground hover:text-foreground hover:border-foreground",
        )}
      >
        Export CSV
      </button>
    </div>
  );
}
