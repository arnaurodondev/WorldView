/**
 * features/portfolio/hooks/useTransactionsFilterState.ts — URL-synced filter state
 * for the Transactions tab (PRD-0089 SA-C).
 *
 * WHY nuqs (not useState): nuqs writes filter values to the URL as query
 * parameters. This means:
 *   1. The user can bookmark a filtered view (e.g. "all BUY transactions from Jan")
 *   2. Browser back/forward correctly restores filter state
 *   3. Filters survive a page refresh without extra persistence code
 *
 * WHY 8 separate useQueryState calls (not useQueryStates): each parameter can
 * be individually reset to its default without touching the others. The batch
 * setFilters() helper updates all 8 at once when needed (e.g. import from URL).
 *
 * PARAMETER NAMES: txType, txFrom, txTo, txTicker, txMin, txMax, txCcy, txSearch
 * — all prefixed with "tx" to avoid collisions with other page-level URL params
 * (e.g. screener or news filters that might share the same page URL).
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 */

"use client";
// WHY "use client": useQueryState relies on the Next.js router which only exists
// in the browser. This hook cannot be called from a server component.

import { useQueryState, parseAsString } from "nuqs";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * TransactionFilters — all 8 filter dimensions for the transactions table.
 *
 * WHY strings (not typed unions) for most fields: nuqs serialises all state to
 * strings in the URL. Using string type throughout avoids repeated casting at
 * the hook boundary. The consumer (TransactionsFilterBar) validates values
 * before rendering chips or comparing against rows.
 */
export interface TransactionFilters {
  /** "All" | "BUY" | "SELL" | "DIV" | "SPLIT" | "TRSF" — active type pill */
  type: string;
  /** YYYY-MM-DD or "" — lower bound for executed_at date comparison */
  dateFrom: string;
  /** YYYY-MM-DD or "" — upper bound for executed_at date comparison */
  dateTo: string;
  /** Ticker substring filter, case-insensitive */
  ticker: string;
  /** Minimum absolute amount (stringified number or "") */
  minAmount: string;
  /** Maximum absolute amount (stringified number or "") */
  maxAmount: string;
  /** "Any" | "USD" | "CAD" | "EUR" | "GBP" — currency filter */
  currency: string;
  /** Free-text search across ticker + type + notes */
  search: string;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useTransactionsFilterState — 8-slot URL-synced filter state for transactions.
 *
 * Returns:
 *   filters     — current values (always defined, never undefined — defaults applied)
 *   setFilters  — batch-update all 8 slots at once (used by TransactionsFilterBar.onChange)
 *   resetFilters — restore all 8 to their defaults (used by the Reset button)
 *
 * USAGE:
 *   const { filters, setFilters, resetFilters } = useTransactionsFilterState();
 *   <TransactionsFilterBar value={filters} onChange={setFilters} ... />
 */
export function useTransactionsFilterState() {
  // WHY parseAsString.withDefault(...): nuqs returns null for absent URL params;
  // withDefault(...) converts null → the default so consumers never have to
  // null-check — every field is always a string.

  // Transaction type — "All" means no filter active.
  const [type, setType] = useQueryState(
    "txType",
    parseAsString.withDefault("All"),
  );

  // Date range — empty string means no bound applied.
  const [dateFrom, setDateFrom] = useQueryState(
    "txFrom",
    parseAsString.withDefault(""),
  );
  const [dateTo, setDateTo] = useQueryState(
    "txTo",
    parseAsString.withDefault(""),
  );

  // Ticker substring — empty string means no ticker filter.
  const [ticker, setTicker] = useQueryState(
    "txTicker",
    parseAsString.withDefault(""),
  );

  // Amount range — empty string means no bound.
  const [minAmount, setMinAmount] = useQueryState(
    "txMin",
    parseAsString.withDefault(""),
  );
  const [maxAmount, setMaxAmount] = useQueryState(
    "txMax",
    parseAsString.withDefault(""),
  );

  // Currency — empty string means "Any" (no currency filter).
  const [currency, setCurrency] = useQueryState(
    "txCcy",
    parseAsString.withDefault(""),
  );

  // Free-text search across ticker + type + notes.
  const [search, setSearch] = useQueryState(
    "txSearch",
    parseAsString.withDefault(""),
  );

  // ── Assembled object ────────────────────────────────────────────────────
  // WHY re-assemble into a plain object on each render: consumers receive one
  // stable shape to destructure. If we added a 9th filter tomorrow the only
  // change needed is here — consumers don't have to update their destructuring.
  const filters: TransactionFilters = {
    type,
    dateFrom,
    dateTo,
    ticker,
    minAmount,
    maxAmount,
    currency,
    search,
  };

  // ── Batch setter ────────────────────────────────────────────────────────
  /**
   * setFilters — update all 8 filter values at once.
   *
   * WHY all-at-once: TransactionsFilterBar.onChange is called with a full
   * filter snapshot rather than individual field updates. This prevents
   * intermediate render states where, e.g., type changed but dateFrom hasn't
   * caught up yet.
   *
   * NOTE: nuqs does NOT batch URL writes by default — each setX call pushes a
   * new history entry. For a fully batched URL push, wrap this function body
   * in `startTransition` at the call site if needed. For most filter
   * interactions (clicking a pill, typing in a box) the current behaviour is
   * acceptable.
   */
  function setFilters(f: TransactionFilters) {
    void setType(f.type);
    void setDateFrom(f.dateFrom);
    void setDateTo(f.dateTo);
    void setTicker(f.ticker);
    void setMinAmount(f.minAmount);
    void setMaxAmount(f.maxAmount);
    void setCurrency(f.currency);
    void setSearch(f.search);
  }

  // ── Reset helper ────────────────────────────────────────────────────────
  /**
   * resetFilters — restore all 8 filter slots to their defaults.
   *
   * Calling setX(null) tells nuqs to remove the parameter from the URL entirely
   * (equivalent to withDefault value). This is cleaner than setX("All") because
   * it produces a shorter URL and is idempotent.
   *
   * WHY void: the return value of setX (a Promise) is intentionally discarded.
   * nuqs state updates are synchronous for the React render; the Promise resolves
   * the Next.js router history push which we don't need to await.
   */
  function resetFilters() {
    void setType(null);      // → "All" (default)
    void setDateFrom(null);  // → ""
    void setDateTo(null);    // → ""
    void setTicker(null);    // → ""
    void setMinAmount(null); // → ""
    void setMaxAmount(null); // → ""
    void setCurrency(null);  // → ""
    void setSearch(null);    // → ""
  }

  return { filters, setFilters, resetFilters };
}
