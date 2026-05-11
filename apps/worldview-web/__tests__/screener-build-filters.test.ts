/**
 * __tests__/screener-build-filters.test.ts — Unit tests for buildScreenerFilters
 *
 * WHY THIS EXISTS: buildScreenerFilters is the translation layer between the
 * screener UI state (FilterState) and the POST /v1/fundamentals/screen payload.
 * Bugs here silently produce wrong results: missing default filters mean entire
 * columns come back NULL from the backend (no constraint → no value computed).
 *
 * Part 4 fix: daily_return and pe_ratio must ALWAYS appear in the output
 * regardless of user input so the backend computes those columns on every row.
 * These tests verify that invariant and guard against regression.
 *
 * DATA SOURCE: app/(app)/screener/page.tsx (buildScreenerFilters)
 * DESIGN REFERENCE: PRD-0031 §7, PLAN-0028 Part 4
 */

import { describe, it, expect } from "vitest";
import { buildScreenerFilters } from "@/features/screener/lib/build-filters";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Find a filter by metric name */
function findFilter(filters: ReturnType<typeof buildScreenerFilters>, metric: string) {
  return filters.find((f) => f.metric === metric);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("buildScreenerFilters — no mandatory enrichment defaults (BP-368 fix)", () => {
  it("does NOT include daily_return by default — INNER JOIN excluded 23/31 instruments", () => {
    // WHY removed: only 8/31 instruments have daily_return data; mandatory filter
    // meant the default screener view always returned 0 (when current_price was
    // also present) or only 8 stocks.
    const filters = buildScreenerFilters(DEFAULT_FILTERS);
    const dr = findFilter(filters, "daily_return");
    expect(dr).toBeUndefined();
  });

  it("does NOT include pe_ratio by default — instruments without earnings data were excluded", () => {
    const filters = buildScreenerFilters(DEFAULT_FILTERS);
    const pe = findFilter(filters, "pe_ratio");
    expect(pe).toBeUndefined();
  });

  it("includes user-specified pe_ratio when explicitly set", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      peMin: 10,
      peMax: 30,
    });
    const peFilters = filters.filter((f) => f.metric === "pe_ratio");
    expect(peFilters).toHaveLength(1);
    expect(peFilters[0].min_value).toBe(10);
    expect(peFilters[0].max_value).toBe(30);
  });

  it("returns empty filters when no user filters set (S3 v2 accepts filters:[])", () => {
    // WHY empty: S3 v2 accepts an empty filters[] and uses the optimised
    // "no filter" path. The mandatory market_capitalization fallback was
    // removed by the BP-368 fix to stop INNER JOIN from narrowing results.
    const filters = buildScreenerFilters(DEFAULT_FILTERS);
    expect(filters.length).toBe(0);
  });

  it("user-specified pe_ratio appears in output at its position in the filter list", () => {
    const filters = buildScreenerFilters({
      ...DEFAULT_FILTERS,
      peMin: 5,
      peMax: 25,
    });
    const peIdx = filters.findIndex((f) => f.metric === "pe_ratio");
    expect(peIdx).toBeGreaterThan(-1);
    expect(filters[peIdx].min_value).toBe(5);
  });
});
