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

// ── PRD-0089 Wave I-B Block IB-L2 — fundamentals snapshot attribute filters ──

describe("buildScreenerFilters — Wave L-2 snapshot filters (IB-L2)", () => {
  it("attaches avg_volume_30d_min to the first filter when set", () => {
    // WHY: same collapse pattern as the IB-L1 categorical attributes. The
    // Wave L-2 backend (commit e1a0193f) dedupes the snapshot predicate
    // across repeated filter entries — we therefore only need to send it
    // on one entry. Pin the contract here so a regression that adds a
    // second carrier filter is caught immediately.
    const filters = buildScreenerFilters(
      makeFilters({ peMin: 10, avgVolume30dMin: 1_000_000 }),
    );
    expect(filters[0].avg_volume_30d_min).toBe(1_000_000);
  });

  it("synthesises a market_cap carrier when only L-2 ranges are set", () => {
    // WHY: when there is no other range filter, the build still has to
    // produce a non-empty filters[] so the backend sees the L-2 attributes.
    const filters = buildScreenerFilters(makeFilters({ epsTtmMin: 1.5 }));
    expect(filters.length).toBe(1);
    expect(filters[0].metric).toBe("market_capitalization");
    expect(filters[0].eps_ttm_min).toBe(1.5);
    // The carrier should not also carry a numeric range — it's restriction-only.
    expect(filters[0].min_value).toBeUndefined();
    expect(filters[0].max_value).toBeUndefined();
  });

  it("forwards all 6 numeric snap fields as scalar min/max wire fields", () => {
    const filters = buildScreenerFilters(
      makeFilters({
        avgVolume30dMin: 1e6,
        avgVolume30dMax: 1e9,
        epsTtmMin: -5,
        epsTtmMax: 50,
        freeCashFlowMin: 1e8,
        freeCashFlowMax: 1e11,
        fcfMarginMin: 0.05,
        fcfMarginMax: 0.5,
        interestCoverageMin: 1.5,
        interestCoverageMax: 20,
        netDebtToEbitdaMin: -2,
        netDebtToEbitdaMax: 4,
      }),
    );
    const f = filters[0];
    expect(f.avg_volume_30d_min).toBe(1e6);
    expect(f.avg_volume_30d_max).toBe(1e9);
    expect(f.eps_ttm_min).toBe(-5);
    expect(f.eps_ttm_max).toBe(50);
    expect(f.free_cash_flow_min).toBe(1e8);
    expect(f.free_cash_flow_max).toBe(1e11);
    expect(f.fcf_margin_min).toBe(0.05);
    expect(f.fcf_margin_max).toBe(0.5);
    expect(f.interest_coverage_min).toBe(1.5);
    expect(f.interest_coverage_max).toBe(20);
    expect(f.net_debt_to_ebitda_min).toBe(-2);
    expect(f.net_debt_to_ebitda_max).toBe(4);
  });

  it("forwards credit_ratings as a list (multi-select round-trip)", () => {
    // WHY a list (not first-entry only as in country/exchange): Wave L-2
    // backend natively supports IN-list on credit_rating
    // (fundamental_metrics_query.py:340). Pinning this protects the
    // multi-select UX from accidentally regressing to the IB-L1 pattern.
    const filters = buildScreenerFilters(
      makeFilters({ creditRatings: ["AA-", "A+", "BBB-"] }),
    );
    expect(filters[0].credit_ratings).toEqual(["AA-", "A+", "BBB-"]);
  });

  it("does NOT emit credit_ratings when the array is empty", () => {
    // Empty array = no filter. Sending [] to the backend would translate to
    // "WHERE credit_rating IN ()" which is invalid SQL.
    const filters = buildScreenerFilters(makeFilters({ creditRatings: [] }));
    expect(filters.length).toBe(0);
  });

  it("does NOT emit ranges when the field is undefined", () => {
    // Default state: no snapshot filter at all → empty filters[].
    const filters = buildScreenerFilters(makeFilters());
    expect(filters.length).toBe(0);
  });
});

describe("buildScreenerFilters — empty filter list (S3 v2 BP-368 fix)", () => {
  it("returns empty array when all inputs are at defaults (S3 v2 accepts filters:[])", () => {
    // WHY empty: S3 v2 ScreenerRequest accepts an empty filters[] and responds
    // with the optimised "no filter" path — returning all instruments. The
    // old mandatory market_capitalization fallback was removed because it
    // caused INNER JOIN narrowing and confused the "all instruments" intent.
    const filters = buildScreenerFilters(makeFilters());
    expect(filters.length).toBe(0);
  });

  it("no mandatory enrichment filters included in empty default state", () => {
    // daily_return and market_capitalization are not automatically injected —
    // they were removed as part of BP-368 fix (INNER JOIN exclusion issue).
    const filters = buildScreenerFilters(makeFilters());
    const hasMarketCap = filters.some((f) => f.metric === "market_capitalization");
    const hasDailyReturn = filters.some((f) => f.metric === "daily_return");
    expect(hasMarketCap).toBe(false);
    expect(hasDailyReturn).toBe(false);
  });
});
