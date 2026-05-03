/**
 * __tests__/apply-client-filters.test.ts — Unit tests for applyClientFilters
 *
 * WHY THIS EXISTS: applyClientFilters is the only screener filter that runs in
 * the browser (backend does not support full-text search). Bugs here silently
 * drop rows that the user expects to see — a finance user misses AAPL because
 * a null-safety bug treated null.toLowerCase() as a crash and the filter never
 * matched anything. These tests enforce the "conservative" rule: a row with
 * missing data is KEPT, not dropped.
 *
 * DATA SOURCE: Pure function — no network, no React context.
 * DESIGN REFERENCE: PLAN-0059 F-C-004, QA report 2026-05-03.
 */

import { describe, it, expect } from "vitest";
import { applyClientFilters } from "@/features/screener/lib/apply-client-filters";
import type { ScreenerResult } from "@/types/api";
import type { FilterState } from "@/features/screener/lib/filter-state";

// ── Helpers ────────────────────────────────────────────────────────────────────

function makeRow(overrides: Partial<ScreenerResult> = {}): ScreenerResult {
  return {
    instrument_id: "uuid-001",
    entity_id: "uuid-001",
    ticker: "TEST",
    name: "Test Corp",
    exchange: null,
    gics_sector: null,
    current_price: null,
    market_cap: null,
    pe_ratio: null,
    daily_return: null,
    revenue: null,
    beta: null,
    market_impact_score: null,
    ...overrides,
  } as ScreenerResult;
}

/** Minimal FilterState with only the fields applyClientFilters reads. */
function makeFilters(overrides: Partial<FilterState> = {}): FilterState {
  return {
    search: "",
    sector: "ALL",
    capTier: "ALL",
    peMin: undefined,
    peMax: undefined,
    pbMin: undefined,
    pbMax: undefined,
    psMin: undefined,
    psMax: undefined,
    evEbitdaMin: undefined,
    evEbitdaMax: undefined,
    roeMin: undefined,
    roeMax: undefined,
    roa: undefined,
    roaMin: undefined,
    roaMax: undefined,
    netMarginMin: undefined,
    netMarginMax: undefined,
    revenueGrowthMin: undefined,
    revenueGrowthMax: undefined,
    epsGrowthMin: undefined,
    epsGrowthMax: undefined,
    debtEquityMin: undefined,
    debtEquityMax: undefined,
    currentRatioMin: undefined,
    currentRatioMax: undefined,
    dividendYieldMin: undefined,
    dividendYieldMax: undefined,
    betaMin: undefined,
    betaMax: undefined,
    above50dMA: false,
    rsiMin: undefined,
    rsiMax: undefined,
    volumeVsAvg: "ANY",
    nearHigh52w: false,
    nearLow52w: false,
    sentimentBias: "ANY",
    minArticles: undefined,
    minImpactScore: undefined,
    ...overrides,
  } as FilterState;
}

// ── Empty search (no-op) ────────────────────────────────────────────────────────

describe("applyClientFilters — empty search", () => {
  it("returns all rows when search is empty string", () => {
    const rows = [makeRow({ ticker: "AAPL" }), makeRow({ ticker: "MSFT" })];
    expect(applyClientFilters(rows, makeFilters({ search: "" }))).toHaveLength(2);
  });

  it("returns all rows when search is whitespace-only", () => {
    const rows = [makeRow({ ticker: "AAPL" }), makeRow({ ticker: "MSFT" })];
    expect(applyClientFilters(rows, makeFilters({ search: "   " }))).toHaveLength(2);
  });

  it("returns empty array unchanged when rows is empty", () => {
    expect(applyClientFilters([], makeFilters({ search: "AAPL" }))).toHaveLength(0);
  });
});

// ── Case-insensitive ticker match ──────────────────────────────────────────────

describe("applyClientFilters — ticker search", () => {
  it("matches exact ticker case-insensitively", () => {
    const rows = [makeRow({ ticker: "AAPL" }), makeRow({ ticker: "MSFT" })];
    const result = applyClientFilters(rows, makeFilters({ search: "aapl" }));
    expect(result).toHaveLength(1);
    expect(result[0].ticker).toBe("AAPL");
  });

  it("matches partial ticker substring", () => {
    const rows = [
      makeRow({ ticker: "AAPL" }),
      makeRow({ ticker: "AAPLSUB" }),
      makeRow({ ticker: "MSFT" }),
    ];
    const result = applyClientFilters(rows, makeFilters({ search: "AAPL" }));
    expect(result).toHaveLength(2);
  });

  it("is case-insensitive for uppercase search against lowercase ticker", () => {
    const rows = [makeRow({ ticker: "goog" })];
    const result = applyClientFilters(rows, makeFilters({ search: "GOOG" }));
    expect(result).toHaveLength(1);
  });
});

// ── Case-insensitive name match ────────────────────────────────────────────────

describe("applyClientFilters — name search", () => {
  it("matches name substring case-insensitively", () => {
    const rows = [
      makeRow({ ticker: "AAPL", name: "Apple Inc" }),
      makeRow({ ticker: "MSFT", name: "Microsoft Corporation" }),
    ];
    const result = applyClientFilters(rows, makeFilters({ search: "apple" }));
    expect(result).toHaveLength(1);
    expect(result[0].ticker).toBe("AAPL");
  });

  it("matches name when ticker does not match", () => {
    const rows = [makeRow({ ticker: "XYZ", name: "Apple Technology Corp" })];
    const result = applyClientFilters(rows, makeFilters({ search: "apple" }));
    expect(result).toHaveLength(1);
  });
});

// ── Null safety ────────────────────────────────────────────────────────────────

describe("applyClientFilters — null ticker/name safety", () => {
  it("keeps rows with null ticker when search does not match name either", () => {
    // WHY: conservative rule — missing data means "uncertain", not "exclude".
    // A null ticker must not throw or silently drop the row.
    const rows = [makeRow({ ticker: null as unknown as string, name: "Some Corp" })];
    const result = applyClientFilters(rows, makeFilters({ search: "zzz" }));
    // No match on name either → row is excluded (not kept due to null)
    expect(result).toHaveLength(0);
  });

  it("keeps rows with null ticker when name matches search", () => {
    const rows = [makeRow({ ticker: null as unknown as string, name: "Apple Inc" })];
    const result = applyClientFilters(rows, makeFilters({ search: "apple" }));
    expect(result).toHaveLength(1);
  });

  it("keeps rows with null name when ticker matches search", () => {
    const rows = [makeRow({ ticker: "AAPL", name: null as unknown as string })];
    const result = applyClientFilters(rows, makeFilters({ search: "aapl" }));
    expect(result).toHaveLength(1);
  });

  it("keeps rows with both null ticker and name when there is no search", () => {
    const rows = [makeRow({ ticker: null as unknown as string, name: null as unknown as string })];
    expect(applyClientFilters(rows, makeFilters({ search: "" }))).toHaveLength(1);
  });
});
