/**
 * features/portfolio/hooks/__tests__/useTransactionsFilterState.test.ts (F-010)
 *
 * WHY: Verifies the URL-synced filter hook contract:
 *  1. Defaults: all fields start with their default values (type="All", others "").
 *  2. setFilters: batch-updates all 8 fields.
 *  3. resetFilters: restores all 8 fields to their defaults.
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
});
