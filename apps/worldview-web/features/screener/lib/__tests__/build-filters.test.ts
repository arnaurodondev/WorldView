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

// ── IB-L5 — Intelligence rollup filters ──────────────────────────────────────

describe("buildScreenerFilters — IB-L5 intelligence rollup metric names", () => {
  it("newsCount7d maps to 'news_count_7d'", () => {
    // WHY: metric name must match the exact column name in
    // instrument_fundamentals_snapshot; mismatches are silently dropped.
    const filters = buildScreenerFilters(makeFilters({ newsCount7dMin: 3 }));
    const f = findFilter(filters, "news_count_7d");
    expect(f?.min_value).toBe(3);
    expect(f?.max_value).toBeUndefined();
  });

  it("newsCount7d max is also mapped", () => {
    const filters = buildScreenerFilters(makeFilters({ newsCount7dMin: 2, newsCount7dMax: 50 }));
    const f = findFilter(filters, "news_count_7d");
    expect(f?.min_value).toBe(2);
    expect(f?.max_value).toBe(50);
  });

  it("llmRelevance7d maps to 'llm_relevance_7d_max'", () => {
    const filters = buildScreenerFilters(makeFilters({ llmRelevance7dMin: 0.6 }));
    const f = findFilter(filters, "llm_relevance_7d_max");
    expect(f?.min_value).toBe(0.6);
  });

  it("displayRelevance7d maps to 'display_relevance_7d_weighted'", () => {
    const filters = buildScreenerFilters(makeFilters({ displayRelevance7dMin: 0.5, displayRelevance7dMax: 1 }));
    const f = findFilter(filters, "display_relevance_7d_weighted");
    expect(f?.min_value).toBe(0.5);
    expect(f?.max_value).toBe(1);
  });

  it("contradictions maps to 'recent_contradiction_count'", () => {
    const filters = buildScreenerFilters(makeFilters({ contradictionsMin: 1 }));
    const f = findFilter(filters, "recent_contradiction_count");
    expect(f?.min_value).toBe(1);
  });

  it("hasAiBrief=true adds has_ai_brief filter with min_value=1", () => {
    // WHY min_value=1: boolean columns in S3 are filtered via a range check
    // WHERE col >= 1, which is equivalent to WHERE col = TRUE for booleans.
    const filters = buildScreenerFilters(makeFilters({ hasAiBrief: true }));
    const f = findFilter(filters, "has_ai_brief");
    expect(f).toBeDefined();
    expect(f?.min_value).toBe(1);
  });

  it("hasAiBrief=false does NOT add a has_ai_brief filter", () => {
    // WHY: false means "no filter" (show all), not "must NOT have brief".
    const filters = buildScreenerFilters(makeFilters({ hasAiBrief: false }));
    expect(findFilter(filters, "has_ai_brief")).toBeUndefined();
  });

  it("hasAiBrief=undefined does NOT add a has_ai_brief filter", () => {
    const filters = buildScreenerFilters(makeFilters());
    expect(findFilter(filters, "has_ai_brief")).toBeUndefined();
  });

  it("hasActiveAlert=true adds has_active_alert filter with min_value=1", () => {
    const filters = buildScreenerFilters(makeFilters({ hasActiveAlert: true }));
    const f = findFilter(filters, "has_active_alert");
    expect(f).toBeDefined();
    expect(f?.min_value).toBe(1);
  });

  it("hasActiveAlert=false does NOT add a has_active_alert filter", () => {
    const filters = buildScreenerFilters(makeFilters({ hasActiveAlert: false }));
    expect(findFilter(filters, "has_active_alert")).toBeUndefined();
  });

  it("no intelligence filters are emitted when all IB-L5 fields are at defaults", () => {
    // WHY: ensures the default screener (no filters set) doesn't silently add
    // intelligence constraints that would narrow the universe unexpectedly.
    const filters = buildScreenerFilters(makeFilters());
    const intelligenceMetrics = [
      "news_count_7d",
      "llm_relevance_7d_max",
      "display_relevance_7d_weighted",
      "recent_contradiction_count",
      "has_ai_brief",
      "has_active_alert",
    ];
    for (const metric of intelligenceMetrics) {
      expect(findFilter(filters, metric)).toBeUndefined();
    }
  });
});
