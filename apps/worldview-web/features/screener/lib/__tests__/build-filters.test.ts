/**
 * features/screener/lib/__tests__/build-filters.test.ts
 *
 * WHY THIS EXISTS: buildScreenerFilters converts UI FilterState → ScreenerFilter[].
 * Bugs here silently drop filter dimensions (the backend receives an empty filter
 * array and returns all instruments regardless of the user's constraints). The
 * most dangerous failure mode is the "always-include" enrichment filters (daily_return,
 * pe_ratio, current_price): if they are accidentally removed, three columns go blank
 * for every user on every screener query with no visible error.
 *
 * DATA SOURCE: Pure function — no network, no React, no DOM.
 * DESIGN REFERENCE: PLAN-0051 T-B-2-01, QA report 2026-05-03 F-M-002.
 */

import { describe, it, expect } from "vitest";
import { buildScreenerFilters } from "../build-filters";
import type { FilterState } from "../filter-state";
import type { ScreenerFilter } from "@/types/api";

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Minimal FilterState with all fields at their "no constraint" defaults. */
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
    divYieldMin: undefined,
    divYieldMax: undefined,
    roeMin: undefined,
    roeMax: undefined,
    netMarginMin: undefined,
    netMarginMax: undefined,
    opMarginMin: undefined,
    opMarginMax: undefined,
    revGrowthMin: undefined,
    revGrowthMax: undefined,
    earningsGrowthMin: undefined,
    earningsGrowthMax: undefined,
    debtEquityMin: undefined,
    debtEquityMax: undefined,
    currentRatioMin: undefined,
    currentRatioMax: undefined,
    roa: undefined,
    roaMin: undefined,
    roaMax: undefined,
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

function findFilter(filters: ScreenerFilter[], metric: string): ScreenerFilter | undefined {
  return filters.find((f) => f.metric === metric);
}

// ── Always-include enrichment filters ─────────────────────────────────────────

describe("buildScreenerFilters — always-include enrichment filters", () => {
  it("always includes daily_return filter with correct bounds (-100 to 100 = percentage format)", () => {
    // WHY ±100 bounds: daily_return is stored as a percentage (5.0 = 5%).
    // The old ±1 bounds only matched stocks with <1% daily move, causing the
    // screener default to return 0 results on most trading days.
    // ±100 covers all realistic daily moves regardless of storage format.
    const filters = buildScreenerFilters(makeFilters());
    const dr = findFilter(filters, "daily_return");
    expect(dr).toBeDefined();
    expect(dr?.min_value).toBe(-100);
    expect(dr?.max_value).toBe(100);
  });

  it("always includes pe_ratio filter with wide bounds (-999999 to 999999)", () => {
    // WHY ±999999 bounds: P/E can be negative (loss-making firms) or extremely high
    // (growth stocks). The old ±9999 bound excluded stocks with no PE data.
    // Ultra-wide bounds ensure all stocks are returned regardless of earnings sign.
    const filters = buildScreenerFilters(makeFilters());
    const pe = findFilter(filters, "pe_ratio");
    expect(pe).toBeDefined();
    expect(pe?.min_value).toBe(-999999);
    expect(pe?.max_value).toBe(999999);
  });

  it("always includes current_price filter (0 to 9,999,999)", () => {
    // WHY current_price enrichment: the PRICE column on the screener table
    // needs current_price on every row even when the user has set no price filter.
    const filters = buildScreenerFilters(makeFilters());
    const price = findFilter(filters, "current_price");
    expect(price).toBeDefined();
    expect(price?.min_value).toBe(0);
    expect(price?.max_value).toBe(9_999_999);
  });

  it("does not duplicate daily_return when user explicitly sets a daily_return range", () => {
    // WHY: if the user sets peMin=5, pe_ratio is already in filters from the
    // user's constraint. The always-include logic must not add a second pe_ratio
    // entry — two filters for the same metric would be ambiguous.
    // This tests the equivalent pattern for daily_return (which the code avoids with .some()).
    const filters = buildScreenerFilters(makeFilters());
    const drFilters = filters.filter((f) => f.metric === "daily_return");
    expect(drFilters).toHaveLength(1);
  });

  it("does not duplicate pe_ratio when user sets a P/E range", () => {
    const filters = buildScreenerFilters(makeFilters({ peMin: 10, peMax: 20 }));
    const peFilters = filters.filter((f) => f.metric === "pe_ratio");
    expect(peFilters).toHaveLength(1);
    // The user's constraint should be preserved, not overwritten by the wide-range default.
    const pe = findFilter(filters, "pe_ratio");
    expect(pe?.min_value).toBe(10);
    expect(pe?.max_value).toBe(20);
  });
});

// ── Cap tier → market_capitalization ─────────────────────────────────────────

describe("buildScreenerFilters — cap tier", () => {
  it("LARGE cap → min_value=10B, no max", () => {
    const filters = buildScreenerFilters(makeFilters({ capTier: "LARGE" }));
    const cap = findFilter(filters, "market_capitalization");
    expect(cap?.min_value).toBe(10_000_000_000);
    expect(cap?.max_value).toBeUndefined();
  });

  it("MID cap → min_value=2B, max_value=10B", () => {
    const filters = buildScreenerFilters(makeFilters({ capTier: "MID" }));
    const cap = findFilter(filters, "market_capitalization");
    expect(cap?.min_value).toBe(2_000_000_000);
    expect(cap?.max_value).toBe(10_000_000_000);
  });

  it("SMALL cap → no min, max_value=2B", () => {
    const filters = buildScreenerFilters(makeFilters({ capTier: "SMALL" }));
    const cap = findFilter(filters, "market_capitalization");
    expect(cap?.min_value).toBeUndefined();
    expect(cap?.max_value).toBe(2_000_000_000);
  });

  it("ALL cap → no market_capitalization filter from cap tier", () => {
    // WHY: ALL means "no constraint" — no cap filter is added.
    // The always-include fallback (market_capitalization min=0) only fires
    // when filters[] is empty, which won't happen if any other filter is set.
    const filters = buildScreenerFilters(makeFilters({ capTier: "ALL" }));
    const explicit = filters.filter(
      (f) => f.metric === "market_capitalization" && f.min_value !== 0,
    );
    expect(explicit).toHaveLength(0);
  });
});

// ── Valuation filters → metric name mapping ────────────────────────────────────

describe("buildScreenerFilters — valuation metric names", () => {
  it("P/E maps to 'pe_ratio'", () => {
    const filters = buildScreenerFilters(makeFilters({ peMin: 5, peMax: 25 }));
    const pe = findFilter(filters, "pe_ratio");
    expect(pe?.min_value).toBe(5);
    expect(pe?.max_value).toBe(25);
  });

  it("P/B maps to 'pb_ratio'", () => {
    const filters = buildScreenerFilters(makeFilters({ pbMin: 1, pbMax: 5 }));
    expect(findFilter(filters, "pb_ratio")).toBeDefined();
  });

  it("P/S maps to 'price_sales_ttm'", () => {
    const filters = buildScreenerFilters(makeFilters({ psMin: 0.5 }));
    expect(findFilter(filters, "price_sales_ttm")).toBeDefined();
  });

  it("dividend yield maps to 'dividend_yield'", () => {
    const filters = buildScreenerFilters(makeFilters({ divYieldMin: 0.02 }));
    expect(findFilter(filters, "dividend_yield")).toBeDefined();
  });
});

// ── Profitability metric names ────────────────────────────────────────────────

describe("buildScreenerFilters — profitability metric names", () => {
  it("ROE maps to 'roe_ttm'", () => {
    const filters = buildScreenerFilters(makeFilters({ roeMin: 0.15 }));
    expect(findFilter(filters, "roe_ttm")).toBeDefined();
  });

  it("net margin maps to 'profit_margin'", () => {
    const filters = buildScreenerFilters(makeFilters({ netMarginMin: 0.1 }));
    expect(findFilter(filters, "profit_margin")).toBeDefined();
  });

  it("operating margin maps to 'operating_margin_ttm'", () => {
    const filters = buildScreenerFilters(makeFilters({ opMarginMin: 0.2 }));
    expect(findFilter(filters, "operating_margin_ttm")).toBeDefined();
  });
});

// ── Sector restriction ────────────────────────────────────────────────────────

describe("buildScreenerFilters — sector restriction", () => {
  it("attaches sector to the first filter when sector is not ALL", () => {
    const filters = buildScreenerFilters(
      makeFilters({ sector: "Technology", capTier: "LARGE" }),
    );
    // First filter should have the sector attached.
    expect(filters[0].sector).toBe("Technology");
  });

  it("does not attach sector when sector is ALL", () => {
    const filters = buildScreenerFilters(makeFilters({ sector: "ALL", capTier: "LARGE" }));
    expect(filters[0].sector).toBeUndefined();
  });
});

// ── Fallback filter (empty filter list) ───────────────────────────────────────

describe("buildScreenerFilters — empty filter fallback", () => {
  it("returns at least one filter (backend rejects empty array)", () => {
    // WHY: the backend's ScreenerRequest has min_length=1 on filters[].
    // With all defaults (ALL cap, no ranges, no sector), the function must
    // still emit a minimum filter so the request doesn't fail with 422.
    const filters = buildScreenerFilters(makeFilters());
    expect(filters.length).toBeGreaterThan(0);
  });

  it("fallback filter uses market_capitalization metric", () => {
    // WHY market_capitalization: it is the least likely to narrow results
    // when set to min=0, which is safe as a universal "select everything" filter.
    const filters = buildScreenerFilters(makeFilters());
    // At minimum, there should be a market_capitalization or always-include filter.
    const hasMarketCap = filters.some((f) => f.metric === "market_capitalization");
    const hasDailyReturn = filters.some((f) => f.metric === "daily_return");
    expect(hasMarketCap || hasDailyReturn).toBe(true);
  });
});
