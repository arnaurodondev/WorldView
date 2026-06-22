/**
 * features/portfolio/hooks/useTransactionsFilterState.ts — URL-synced filter state
 * for the Transactions tab (PRD-0089 SA-C, PRD-0114 W5-T01).
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
 * BACKEND WIRING (PRD-0114 W5): The hook now derives backend query params from
 * the URL state via toBackendParams() so TransactionsTab can pass them to the
 * S9 API call. The mapping rules:
 *   - txType → transaction_type[] (maps "All" → undefined, "DIV" → "DIVIDEND")
 *   - txFrom/txTo → from_date/to_date (passthrough ISO date strings)
 *   - txTicker → ticker
 * This replaces the old client-side type-toggle filtering that only operated
 * on the current fetched page.
 *
 * PAGINATION RESET (PRD-0114 W5): any filter change should reset to page 1.
 * TransactionsTab calls onTxOffsetChange(0) in its onChange handler so the
 * user sees page 1 of the new filtered result set.
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

/**
 * BackendTransactionParams — typed API query params for the S9 transactions
 * endpoint, derived from TransactionFilters by toBackendParams().
 *
 * WHY undefined instead of null/empty: the API client (apiFetch and raw fetch)
 * should omit undefined values from URLSearchParams construction. Undefined for
 * unset filters means they are absent from the request URL (no filter applied).
 */
export interface BackendTransactionParams {
  from_date?: string;
  to_date?: string;
  /** Server-side TransactionType enum values. "DIVIDEND" maps from the "DIV" pill. */
  transaction_type?: string[];
  ticker?: string;
}

// ── Type mapping ──────────────────────────────────────────────────────────────

/**
 * UI pill label → S1 TransactionType enum value mapping.
 *
 * WHY explicit map (not .toUpperCase()): the UI pills use short labels
 * ("DIV", "TRSF", "SPLIT") that don't match the backend enum values
 * ("DIVIDEND", "TRANSFER"). The map is the single source of truth for
 * this translation.
 */
const PILL_TO_BACKEND: Record<string, string> = {
  BUY: "BUY",
  SELL: "SELL",
  DIV: "DIVIDEND",
  SPLIT: "SPLIT",
  TRSF: "TRANSFER",
};

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useTransactionsFilterState — 8-slot URL-synced filter state for transactions.
 *
 * Returns:
 *   filters          — current values (always defined, never undefined — defaults applied)
 *   setFilters       — batch-update all 8 slots at once (used by TransactionsFilterBar.onChange)
 *   resetFilters     — restore all 8 to their defaults (used by the Reset button)
 *   toBackendParams  — derive typed API query params from the current filter state
 *   hasActiveFilters — true when at least one filter diverges from its default
 *
 * USAGE:
 *   const { filters, setFilters, resetFilters, toBackendParams } = useTransactionsFilterState();
 *   <TransactionsFilterBar value={filters} onChange={setFilters} ... />
 *   const params = toBackendParams(); // pass to getTransactions()
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

  // ── Active filter check ─────────────────────────────────────────────────
  // WHY exported: TransactionsFilterBar uses it to show/hide the Reset button;
  // TransactionsTab uses it to know whether to highlight the filter bar.
  const hasActiveFilters =
    type !== "All" ||
    dateFrom !== "" ||
    dateTo !== "" ||
    ticker !== "" ||
    minAmount !== "" ||
    maxAmount !== "" ||
    currency !== "" ||
    search !== "";

  // ── Backend params derivation ───────────────────────────────────────────
  /**
   * toBackendParams — convert the current URL filter state into typed API
   * query params for the S9 transactions endpoint.
   *
   * WHY a function (not a memoised value): the params are only needed at
   * query-key construction time, not on every render. Keeping it as a function
   * avoids an unnecessary useMemo dependency array.
   *
   * MAPPING RULES:
   *   - type === "All" → transaction_type is undefined (no type filter)
   *   - type === "DIV" → ["DIVIDEND"] (UI label differs from backend enum)
   *   - dateFrom/dateTo empty string → undefined (omit from request)
   *   - ticker empty string → undefined (omit from request)
   */
  function toBackendParams(): BackendTransactionParams {
    const params: BackendTransactionParams = {};

    // Transaction type — only set when a specific type is selected.
    if (type !== "All") {
      const backendType = PILL_TO_BACKEND[type];
      if (backendType) {
        params.transaction_type = [backendType];
      }
    }

    // FE-005: date range validation — if both bounds are present and the range
    // is logically impossible (from > to), omit to_date from the request rather
    // than sending an inverted range that returns 0 rows with no feedback.
    // The dateRangeError field signals the UI to show an inline error.
    // WHY omit to_date (not from_date): the start date is the user's primary
    // intent ("show me transactions since January"); silently dropping the end
    // date is less surprising than dropping the start date. The error message
    // in dateRangeError guides the user to correct the end date.
    if (dateFrom) params.from_date = dateFrom;
    if (dateTo) {
      const rangeInvalid = dateFrom !== "" && dateTo < dateFrom;
      if (!rangeInvalid) {
        params.to_date = dateTo;
      }
      // If rangeInvalid, to_date is intentionally omitted from params.
      // TransactionsFilterBar reads dateRangeError to render the inline message.
    }

    // Ticker — only set when the user typed something.
    if (ticker) params.ticker = ticker;

    return params;
  }

  /**
   * dateRangeError — non-null when from_date > to_date (logically impossible range).
   *
   * FE-005: surface the error to TransactionsFilterBar so it can render an
   * inline validation message below the date inputs. The backend params are
   * still derivable (toBackendParams() silently drops to_date) but the user
   * sees immediate feedback rather than an unexplained empty table.
   */
  const dateRangeError: string | null =
    dateFrom !== "" && dateTo !== "" && dateTo < dateFrom
      ? "End date must be on or after the start date"
      : null;

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
   * in `startTransition` at the call site if needed.
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

  return { filters, setFilters, resetFilters, toBackendParams, hasActiveFilters, dateRangeError };
}
