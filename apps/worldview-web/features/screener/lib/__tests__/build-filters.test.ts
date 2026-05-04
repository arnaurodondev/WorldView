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

// ── No mandatory enrichment filters (removed in BP-368 fix) ─────────────────

describe("buildScreenerFilters — no mandatory enrichment filters", () => {
  it("does NOT always include daily_return — backend INNER JOIN excluded 23/31 instruments", () => {
    // WHY removed: the backend uses INNER JOIN per filter metric.
    // Only 8/31 instruments have daily_return data; adding it as a mandatory
    // filter silently excludes the 23 without that metric.
    // Users who want to filter by daily_return add it explicitly.
    const filters = buildScreenerFilters(makeFilters());
    const dr = findFilter(filters, "daily_return");
    expect(dr).toBeUndefined();
  });

  it("does NOT always include pe_ratio — backend INNER JOIN excluded instruments with no earnings data", () => {
    // WHY removed: same INNER JOIN issue; instruments without PE data
    // (e.g. pre-earnings, negative EPS) would be excluded from default view.
    const filters = buildScreenerFilters(makeFilters());
    const pe = findFilter(filters, "pe_ratio");
    expect(pe).toBeUndefined();
  });

  it("does NOT include current_price — not a valid screener metric, caused 0-result default", () => {
    // WHY: `current_price` does not exist in fundamentals_metrics table.
    // The backend screener fields endpoint doesn't list it. Adding it caused
    // INNER JOIN → 0 results on every default screener load.
    const filters = buildScreenerFilters(makeFilters());
    const price = findFilter(filters, "current_price");
    expect(price).toBeUndefined();
  });

  it("includes user-specified pe_ratio constraint when explicitly set", () => {
    const filters = buildScreenerFilters(makeFilters({ peMin: 10, peMax: 20 }));
    const peFilters = filters.filter((f) => f.metric === "pe_ratio");
    expect(peFilters).toHaveLength(1);
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
