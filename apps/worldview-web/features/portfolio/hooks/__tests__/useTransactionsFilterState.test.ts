/**
 * features/portfolio/hooks/__tests__/useTransactionsFilterState.test.ts (F-010)
 *
 * WHY: Verifies the URL-synced filter hook contract:
 *  1. Defaults: all fields start with their default values (type="All", others "").
 *  2. setFilters: batch-updates all 8 fields.
 *  3. resetFilters: restores all 8 fields to their defaults.
 *  4. toBackendParams: derives correct S9 API params from filter state (PRD-0114 W5).
 *  5. hasActiveFilters: correctly reports when filters diverge from defaults (W5).
 *
 * WHY NuqsTestingAdapter: nuqs reads/writes the URL via Next.js router APIs.
 * In Vitest/jsdom there is no App Router. NuqsTestingAdapter provides a
 * synthetic URL environment so the hook behaves identically to production
 * without requiring a full Next.js rendering context.
 *
 * PATTERN: renderHook + NuqsTestingAdapter — the canonical nuqs testing approach
 * shown in the docs and used by __tests__/url-state.test.tsx in this repo.
 */

import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import React from "react";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactNode } from "react";

import {
  useTransactionsFilterState,
  type TransactionFilters,
} from "../useTransactionsFilterState";

// ── Wrapper ───────────────────────────────────────────────────────────────────

// WHY React.createElement (not JSX): this is a .ts file; JSX requires .tsx.
// React.createElement is equivalent and avoids renaming the file.
function wrapper({ children }: { children: ReactNode }) {
  // WHY NuqsTestingAdapter: provides a synthetic URL store that nuqs hooks
  // can read/write without a real browser or Next.js routing context.
  return React.createElement(NuqsTestingAdapter, null, children);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useTransactionsFilterState", () => {
  it("returns default values on first render", () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    const { filters } = result.current;

    // WHY "All" (not ""): the type field defaults to "All" per withDefault("All").
    expect(filters.type).toBe("All");
    // All string-range fields default to empty string.
    expect(filters.dateFrom).toBe("");
    expect(filters.dateTo).toBe("");
    expect(filters.ticker).toBe("");
    expect(filters.minAmount).toBe("");
    expect(filters.maxAmount).toBe("");
    expect(filters.currency).toBe("");
    expect(filters.search).toBe("");
  });

  it("setFilters updates all 8 filter dimensions at once", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    const newFilters: TransactionFilters = {
      type: "BUY",
      dateFrom: "2026-01-01",
      dateTo: "2026-05-23",
      ticker: "AAPL",
      minAmount: "100",
      maxAmount: "5000",
      currency: "USD",
      search: "apple",
    };

    await act(async () => {
      result.current.setFilters(newFilters);
    });

    const { filters } = result.current;
    expect(filters.type).toBe("BUY");
    expect(filters.dateFrom).toBe("2026-01-01");
    expect(filters.dateTo).toBe("2026-05-23");
    expect(filters.ticker).toBe("AAPL");
    expect(filters.minAmount).toBe("100");
    expect(filters.maxAmount).toBe("5000");
    expect(filters.currency).toBe("USD");
    expect(filters.search).toBe("apple");
  });

  it("resetFilters restores all fields to their defaults", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    // First set all fields to non-default values.
    await act(async () => {
      result.current.setFilters({
        type: "SELL",
        dateFrom: "2026-01-01",
        dateTo: "2026-12-31",
        ticker: "TSLA",
        minAmount: "500",
        maxAmount: "9999",
        currency: "EUR",
        search: "tesla",
      });
    });

    // Then reset — all fields should return to defaults.
    await act(async () => {
      result.current.resetFilters();
    });

    const { filters } = result.current;
    // WHY "All": resetFilters calls setType(null) which nuqs converts back
    // to the withDefault("All") value.
    expect(filters.type).toBe("All");
    expect(filters.dateFrom).toBe("");
    expect(filters.dateTo).toBe("");
    expect(filters.ticker).toBe("");
    expect(filters.minAmount).toBe("");
    expect(filters.maxAmount).toBe("");
    expect(filters.currency).toBe("");
    expect(filters.search).toBe("");
  });

  // ── QA-F002 regression guard ────────────────────────────────────────────────
  // WHY this exists alongside the previous test: the audit (QA-F002, see
  // docs/audits/2026-05-24-investigation-qa-open-items.md) flagged that
  // resetFilters() is implemented as 8 independent setX(null) calls — if a
  // future refactor drops ONE of those lines, the URL-synced state for that
  // slot would silently keep its previous value. This test pins every slot
  // INDIVIDUALLY so such a regression triggers a precise assertion failure
  // pointing at the missing reset.
  it("resetFilters clears all 8 filter slots individually (D-003, QA-F002)", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    // Set every slot to a non-default value so any forgotten reset is visible.
    await act(async () => {
      result.current.setFilters({
        type: "SELL",
        dateFrom: "2026-01-01",
        dateTo: "2026-12-31",
        ticker: "TSLA",
        minAmount: "1000",
        maxAmount: "50000",
        currency: "EUR",
        search: "tesla",
      });
    });

    await act(async () => {
      result.current.resetFilters();
    });

    // Per-slot assertions — defaults pulled from useTransactionsFilterState.ts:
    // type → withDefault("All"); all others → withDefault("").
    const { filters } = result.current;
    expect(filters.type).toBe("All");
    expect(filters.dateFrom).toBe("");
    expect(filters.dateTo).toBe("");
    expect(filters.ticker).toBe("");
    expect(filters.minAmount).toBe("");
    expect(filters.maxAmount).toBe("");
    expect(filters.currency).toBe("");
    expect(filters.search).toBe("");
  });

  // ── W5 toBackendParams tests ────────────────────────────────────────────────

  it("toBackendParams returns empty object when all filters are at defaults", () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    // WHY empty object: no active filter means no query params should be sent
    // to the backend (omitting them avoids unnecessary filtering overhead on S9).
    const params = result.current.toBackendParams();
    expect(params).toEqual({});
  });

  it("toBackendParams maps type='BUY' → transaction_type=['BUY']", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "BUY",
        dateFrom: "",
        dateTo: "",
        ticker: "",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    const params = result.current.toBackendParams();
    expect(params.transaction_type).toEqual(["BUY"]);
  });

  it("toBackendParams maps type='DIV' → transaction_type=['DIVIDEND']", async () => {
    // WHY this specific mapping: "DIV" is the UI pill label; "DIVIDEND" is the
    // S1 TransactionType enum value. PILL_TO_BACKEND is the single source of truth.
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "DIV",
        dateFrom: "",
        dateTo: "",
        ticker: "",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    const params = result.current.toBackendParams();
    expect(params.transaction_type).toEqual(["DIVIDEND"]);
  });

  it("toBackendParams forwards from_date and to_date when set", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "All",
        dateFrom: "2026-01-01",
        dateTo: "2026-06-30",
        ticker: "",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    const params = result.current.toBackendParams();
    expect(params.from_date).toBe("2026-01-01");
    expect(params.to_date).toBe("2026-06-30");
    // type is "All" → transaction_type should be undefined
    expect(params.transaction_type).toBeUndefined();
  });

  it("toBackendParams forwards ticker when set", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "All",
        dateFrom: "",
        dateTo: "",
        ticker: "NVDA",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    const params = result.current.toBackendParams();
    expect(params.ticker).toBe("NVDA");
  });

  it("toBackendParams combines all active params correctly", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "SELL",
        dateFrom: "2026-03-01",
        dateTo: "2026-03-31",
        ticker: "AAPL",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    const params = result.current.toBackendParams();
    expect(params.transaction_type).toEqual(["SELL"]);
    expect(params.from_date).toBe("2026-03-01");
    expect(params.to_date).toBe("2026-03-31");
    expect(params.ticker).toBe("AAPL");
  });

  // ── W5 hasActiveFilters tests ───────────────────────────────────────────────

  it("hasActiveFilters is false when all filters are at defaults", () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    // No filters active = no visual indicator needed, no API filter params sent.
    expect(result.current.hasActiveFilters).toBe(false);
  });

  it("hasActiveFilters is true when type is set to anything other than 'All'", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "BUY",
        dateFrom: "",
        dateTo: "",
        ticker: "",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    // A non-"All" type means a filter is active.
    expect(result.current.hasActiveFilters).toBe(true);
  });

  it("hasActiveFilters is true when dateFrom is set", async () => {
    const { result } = renderHook(() => useTransactionsFilterState(), {
      wrapper,
    });

    await act(async () => {
      result.current.setFilters({
        type: "All",
        dateFrom: "2026-01-01",
        dateTo: "",
        ticker: "",
        minAmount: "",
        maxAmount: "",
        currency: "",
        search: "",
      });
    });

    expect(result.current.hasActiveFilters).toBe(true);
  });
});
