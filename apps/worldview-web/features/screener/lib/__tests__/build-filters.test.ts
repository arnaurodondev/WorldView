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
import { buildScreenerFilters, nlFiltersToFilterState } from "../build-filters";
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

// ── IB-L5 — Intelligence rollup filters (per-filter named fields) ────────────
//
// WHY the wire format changed (2026-06-09 hotfix): the original IB-L5 ship
// pushed each intelligence field as its own filter entry
// (`{metric: "news_count_7d", min_value: 1}`). That silently dropped every
// IB-L5 filter at the backend INNER JOIN because the metric strings aren't in
// the computed-metrics catalogue. The corrected wire format places the
// intelligence fields as NAMED siblings of `min_value`/`max_value` on a single
// filter object — matching the ScreenFilterRequest schema in
// services/market-data/src/market_data/api/schemas/fundamental_metrics.py.
//
// Tests below verify the *fixed* shape: one filter object carries all live
// intelligence fields plus a synthetic `metric` ("market_capitalization") to
// satisfy the backend's required-metric regex.

describe("buildScreenerFilters — IB-L5 intelligence rollup (per-filter fields)", () => {
  it("newsCount7dMin lands on filter.news_count_7d_min, not as its own filter entry", () => {
    const filters = buildScreenerFilters(makeFilters({ newsCount7dMin: 3 }));
    // No filter entry has metric=news_count_7d (the old broken shape):
    expect(findFilter(filters, "news_count_7d")).toBeUndefined();
    // Instead, ONE filter carries the intelligence field as a named sibling.
    const intelHolder = filters.find((x) => x.news_count_7d_min !== undefined);
    expect(intelHolder?.news_count_7d_min).toBe(3);
    expect(intelHolder?.news_count_7d_max).toBeUndefined();
  });

  it("newsCount7d max also maps to news_count_7d_max named field", () => {
    const filters = buildScreenerFilters(makeFilters({ newsCount7dMin: 2, newsCount7dMax: 50 }));
    const h = filters.find((x) => x.news_count_7d_min !== undefined);
    expect(h?.news_count_7d_min).toBe(2);
    expect(h?.news_count_7d_max).toBe(50);
  });

  it("llmRelevance7d maps to llm_relevance_7d_max_min named field", () => {
    const filters = buildScreenerFilters(makeFilters({ llmRelevance7dMin: 0.6 }));
    const h = filters.find((x) => x.llm_relevance_7d_max_min !== undefined);
    expect(h?.llm_relevance_7d_max_min).toBe(0.6);
  });

  it("displayRelevance7d maps to display_relevance_7d_weighted_{min,max}", () => {
    const filters = buildScreenerFilters(makeFilters({ displayRelevance7dMin: 0.5, displayRelevance7dMax: 1 }));
    const h = filters.find((x) => x.display_relevance_7d_weighted_min !== undefined);
    expect(h?.display_relevance_7d_weighted_min).toBe(0.5);
    expect(h?.display_relevance_7d_weighted_max).toBe(1);
  });

  it("contradictions maps to recent_contradiction_count_min", () => {
    const filters = buildScreenerFilters(makeFilters({ contradictionsMin: 1 }));
    const h = filters.find((x) => x.recent_contradiction_count_min !== undefined);
    expect(h?.recent_contradiction_count_min).toBe(1);
  });

  it("hasAiBrief=true sets has_ai_brief: true on a filter (not a min_value=1 entry)", () => {
    const filters = buildScreenerFilters(makeFilters({ hasAiBrief: true }));
    expect(findFilter(filters, "has_ai_brief")).toBeUndefined(); // old broken shape gone
    const h = filters.find((x) => x.has_ai_brief !== undefined);
    expect(h?.has_ai_brief).toBe(true);
  });

  it("hasAiBrief=false does NOT set has_ai_brief", () => {
    const filters = buildScreenerFilters(makeFilters({ hasAiBrief: false }));
    expect(filters.some((x) => x.has_ai_brief !== undefined)).toBe(false);
  });

  it("hasAiBrief=undefined does NOT set has_ai_brief", () => {
    const filters = buildScreenerFilters(makeFilters());
    expect(filters.some((x) => x.has_ai_brief !== undefined)).toBe(false);
  });

  it("hasActiveAlert=true sets has_active_alert: true", () => {
    const filters = buildScreenerFilters(makeFilters({ hasActiveAlert: true }));
    const h = filters.find((x) => x.has_active_alert !== undefined);
    expect(h?.has_active_alert).toBe(true);
  });

  it("hasActiveAlert=false does NOT set has_active_alert", () => {
    const filters = buildScreenerFilters(makeFilters({ hasActiveAlert: false }));
    expect(filters.some((x) => x.has_active_alert !== undefined)).toBe(false);
  });

  it("no intelligence fields are emitted when all IB-L5 inputs are at defaults", () => {
    const filters = buildScreenerFilters(makeFilters());
    const intelKeys: (keyof import("@/types/api").ScreenerFilter)[] = [
      "news_count_7d_min",
      "news_count_7d_max",
      "llm_relevance_7d_max_min",
      "llm_relevance_7d_max_max",
      "display_relevance_7d_weighted_min",
      "display_relevance_7d_weighted_max",
      "recent_contradiction_count_min",
      "has_ai_brief",
      "has_active_alert",
    ];
    for (const k of intelKeys) {
      expect(filters.some((x) => x[k] !== undefined)).toBe(false);
    }
  });

  it("multiple intelligence fields merge onto a SINGLE filter object", () => {
    // Regression guard: each intelligence field must NOT spawn its own filter
    // entry (the original IB-L5 bug). They all merge onto one object.
    const filters = buildScreenerFilters(
      makeFilters({
        newsCount7dMin: 5,
        contradictionsMin: 1,
        hasAiBrief: true,
        hasActiveAlert: true,
        displayRelevance7dMin: 0.7,
      }),
    );
    const intelHolders = filters.filter(
      (x) =>
        x.news_count_7d_min !== undefined ||
        x.recent_contradiction_count_min !== undefined ||
        x.has_ai_brief !== undefined ||
        x.has_active_alert !== undefined ||
        x.display_relevance_7d_weighted_min !== undefined,
    );
    expect(intelHolders).toHaveLength(1);
    const h = intelHolders[0];
    expect(h.news_count_7d_min).toBe(5);
    expect(h.recent_contradiction_count_min).toBe(1);
    expect(h.has_ai_brief).toBe(true);
    expect(h.has_active_alert).toBe(true);
    expect(h.display_relevance_7d_weighted_min).toBe(0.7);
  });

  it("intelligence-only request creates a synthetic market_capitalization filter (required by backend regex)", () => {
    // When no other range filter is active, the intelligence fields still need
    // a `metric` field — backend regex requires it. Synthetic market_capitalization
    // has no min/max so it carries no extra constraint.
    const filters = buildScreenerFilters(makeFilters({ hasAiBrief: true }));
    expect(filters).toHaveLength(1);
    expect(filters[0].metric).toBe("market_capitalization");
    expect(filters[0].min_value).toBeUndefined();
    expect(filters[0].max_value).toBeUndefined();
    expect(filters[0].has_ai_brief).toBe(true);
  });
});

// ── Round 2: avg_volume_30d named-field range (SERVER_SIDE) ──────────────────
//
// WHY THESE TESTS: avg_volume_30d is a snapshot COLUMN (not a
// fundamental_metrics row), so it must travel as the avg_volume_30d_min/max
// per-filter named fields — the exact same silent-zero-rows trap as the
// intelligence rollup fields above. These tests pin the request shape the
// backend actually parses (ScreenFilterRequest, fundamental_metrics.py:48-49).

describe("buildScreenerFilters — avg volume 30d range (Round 2)", () => {
  it("merges avgVolume30dMin/Max onto an existing filter as named fields (NOT a metric entry)", () => {
    const filters = buildScreenerFilters(
      makeFilters({ peMin: 10, avgVolume30dMin: 500_000, avgVolume30dMax: 50_000_000 }),
    );
    // No `{metric: "avg_volume_30d"}` entry may exist — that shape silently
    // returns 0 rows via the backend's INNER JOIN on unknown metrics.
    expect(findFilter(filters, "avg_volume_30d")).toBeUndefined();
    // The named fields ride on the first filter object.
    const holder = filters.find(
      (f) =>
        (f as Record<string, unknown>).avg_volume_30d_min !== undefined ||
        (f as Record<string, unknown>).avg_volume_30d_max !== undefined,
    ) as Record<string, unknown> | undefined;
    expect(holder).toBeDefined();
    expect(holder?.avg_volume_30d_min).toBe(500_000);
    expect(holder?.avg_volume_30d_max).toBe(50_000_000);
    // And it merged onto the existing pe_ratio filter, not a new entry.
    expect(holder?.metric).toBe("pe_ratio");
  });

  it("volume-only request creates the synthetic market_capitalization carrier filter", () => {
    const filters = buildScreenerFilters(makeFilters({ avgVolume30dMin: 1_000_000 }));
    expect(filters).toHaveLength(1);
    expect(filters[0].metric).toBe("market_capitalization");
    expect(filters[0].min_value).toBeUndefined();
    expect(filters[0].max_value).toBeUndefined();
    expect((filters[0] as Record<string, unknown>).avg_volume_30d_min).toBe(1_000_000);
  });

  it("sends only the side that is set (min-only / max-only)", () => {
    const minOnly = buildScreenerFilters(makeFilters({ avgVolume30dMin: 250_000 }));
    expect((minOnly[0] as Record<string, unknown>).avg_volume_30d_min).toBe(250_000);
    expect((minOnly[0] as Record<string, unknown>).avg_volume_30d_max).toBeUndefined();

    const maxOnly = buildScreenerFilters(makeFilters({ avgVolume30dMax: 10_000_000 }));
    expect((maxOnly[0] as Record<string, unknown>).avg_volume_30d_max).toBe(10_000_000);
    expect((maxOnly[0] as Record<string, unknown>).avg_volume_30d_min).toBeUndefined();
  });

  it("emits nothing volume-related when both sides are unset", () => {
    const filters = buildScreenerFilters(makeFilters());
    for (const f of filters) {
      expect((f as Record<string, unknown>).avg_volume_30d_min).toBeUndefined();
      expect((f as Record<string, unknown>).avg_volume_30d_max).toBeUndefined();
    }
  });

  it("coexists with the intelligence named fields on the same carrier filter", () => {
    // Both blocks use the merge-onto-filters[0] pattern; they must compose,
    // not overwrite each other.
    const filters = buildScreenerFilters(
      makeFilters({ hasAiBrief: true, avgVolume30dMin: 2_000_000 }),
    );
    expect(filters).toHaveLength(1);
    const f = filters[0] as Record<string, unknown>;
    expect(f.has_ai_brief).toBe(true);
    expect(f.avg_volume_30d_min).toBe(2_000_000);
  });
});

// ── BUGFIX 2026-06-15: Ownership snapshot-column named-field range ────────────
//
// WHY THESE TESTS: the five Ownership-section filters (analyst target/consensus,
// insider 90d, institutional ownership, short %) are COLUMNS on
// instrument_fundamentals_snapshot — NOT rows in fundamental_metrics. Before
// this fix they were emitted as `{metric: "short_percent", min_value: ...}`,
// which made the backend INNER JOIN on a non-existent metric row and return
// ZERO results for the whole section (live-verified: total 0). The fix routes
// them as per-filter NAMED siblings (`short_percent_min` etc.) — the exact
// same trap + remedy as the IB-L5 + avg_volume_30d blocks above. These tests
// pin the request shape the backend's ScreenFilterRequest actually parses
// (fundamental_metrics.py:64-71, 109-110).

describe("buildScreenerFilters — ownership snapshot fields (named-field range)", () => {
  // Each (FilterState key → backend named field) pair the fix wires up. The
  // backend matches each pair against an instrument_fundamentals_snapshot
  // column, so the metric-entry form silently returns 0 rows.
  const cases: ReadonlyArray<readonly [keyof FilterState, keyof FilterState, string, string, string]> = [
    ["analystTargetPriceMin", "analystTargetPriceMax", "analyst_target_price_min", "analyst_target_price_max", "analyst_target_price"],
    ["analystConsensusMin", "analystConsensusMax", "analyst_consensus_rating_min", "analyst_consensus_rating_max", "analyst_consensus_rating"],
    ["insiderNetBuy90dMin", "insiderNetBuy90dMax", "insider_net_buy_90d_min", "insider_net_buy_90d_max", "insider_net_buy_90d"],
    ["instOwnPctMin", "instOwnPctMax", "institutional_ownership_pct_min", "institutional_ownership_pct_max", "institutional_ownership_pct"],
    ["shortPctMin", "shortPctMax", "short_percent_min", "short_percent_max", "short_percent"],
  ];

  for (const [minKey, maxKey, minField, maxField, metricName] of cases) {
    it(`${String(minKey)}/${String(maxKey)} → named ${minField}/${maxField}, NOT a {metric:"${metricName}"} entry`, () => {
      const filters = buildScreenerFilters(
        makeFilters({ [minKey]: 1, [maxKey]: 2 } as Partial<FilterState>),
      );
      // The broken metric-entry shape must NOT be present (it returns 0 rows).
      expect(findFilter(filters, metricName)).toBeUndefined();
      // The named fields must ride on a single carrier filter object.
      const holder = filters.find(
        (f) => (f as Record<string, unknown>)[minField] !== undefined,
      ) as Record<string, unknown> | undefined;
      expect(holder).toBeDefined();
      expect(holder?.[minField]).toBe(1);
      expect(holder?.[maxField]).toBe(2);
    });
  }

  it("ownership-only request creates the synthetic market_capitalization carrier", () => {
    // No other range filter is active → a synthetic metric carrier is needed
    // because ScreenFilterRequest requires `metric` (regex-validated), but it
    // applies no numeric bound itself (the snapshot column is LEFT-JOINed).
    const filters = buildScreenerFilters(makeFilters({ shortPctMin: 0.05 }));
    expect(filters).toHaveLength(1);
    expect(filters[0].metric).toBe("market_capitalization");
    expect(filters[0].min_value).toBeUndefined();
    expect(filters[0].max_value).toBeUndefined();
    expect((filters[0] as Record<string, unknown>).short_percent_min).toBe(0.05);
  });

  it("merges onto an existing range filter rather than spawning a new entry", () => {
    const filters = buildScreenerFilters(
      makeFilters({ peMin: 10, instOwnPctMin: 0.6 }),
    );
    const holder = filters.find(
      (f) => (f as Record<string, unknown>).institutional_ownership_pct_min !== undefined,
    ) as Record<string, unknown> | undefined;
    expect(holder).toBeDefined();
    // It rode on the pe_ratio filter, not a separate object.
    expect(holder?.metric).toBe("pe_ratio");
    expect(holder?.institutional_ownership_pct_min).toBe(0.6);
  });

  it("sends only the side that is set (min-only / max-only)", () => {
    const minOnly = buildScreenerFilters(makeFilters({ shortPctMin: 0.02 }));
    expect((minOnly[0] as Record<string, unknown>).short_percent_min).toBe(0.02);
    expect((minOnly[0] as Record<string, unknown>).short_percent_max).toBeUndefined();

    const maxOnly = buildScreenerFilters(makeFilters({ shortPctMax: 0.15 }));
    expect((maxOnly[0] as Record<string, unknown>).short_percent_max).toBe(0.15);
    expect((maxOnly[0] as Record<string, unknown>).short_percent_min).toBeUndefined();
  });

  it("emits nothing ownership-related when all inputs are unset", () => {
    const filters = buildScreenerFilters(makeFilters());
    const ownershipFields = [
      "analyst_target_price_min", "analyst_target_price_max",
      "analyst_consensus_rating_min", "analyst_consensus_rating_max",
      "insider_net_buy_90d_min", "insider_net_buy_90d_max",
      "institutional_ownership_pct_min", "institutional_ownership_pct_max",
      "short_percent_min", "short_percent_max",
    ];
    for (const f of filters) {
      for (const field of ownershipFields) {
        expect((f as Record<string, unknown>)[field]).toBeUndefined();
      }
    }
  });

  it("composes with intelligence + volume named fields on one carrier", () => {
    // All three named-field blocks (intel, volume, ownership) merge onto the
    // same filters[0] carrier — they must compose, not clobber.
    const filters = buildScreenerFilters(
      makeFilters({ hasAiBrief: true, avgVolume30dMin: 2_000_000, shortPctMax: 0.1 }),
    );
    expect(filters).toHaveLength(1);
    const f = filters[0] as Record<string, unknown>;
    expect(f.has_ai_brief).toBe(true);
    expect(f.avg_volume_30d_min).toBe(2_000_000);
    expect(f.short_percent_max).toBe(0.1);
  });
});

// ── IB-L5c calendar windows (2026-06-18) ──────────────────────────────────────

describe("buildScreenerFilters — IB-L5c calendar windows", () => {
  it("maps upcomingEarningsWithinDays to the scalar next_earnings_within_days", () => {
    // Backend contract: next_earnings_within_days is a SCALAR "≤ N days" filter
    // (not a _min/_max pair) — fundamental_metrics.py:80. Send N directly.
    const filters = buildScreenerFilters(makeFilters({ upcomingEarningsWithinDays: 7 }));
    expect(filters).toHaveLength(1);
    const f = filters[0] as Record<string, unknown>;
    expect(f.next_earnings_within_days).toBe(7);
    expect(f.next_earnings_within_days_max).toBeUndefined(); // the wrong field must NOT be sent
    expect(f.metric).toBe("market_capitalization"); // synthetic carrier
  });

  it("maps upcomingDividendWithinDays to the scalar next_dividend_within_days", () => {
    const filters = buildScreenerFilters(makeFilters({ upcomingDividendWithinDays: 14 }));
    const f = filters[0] as Record<string, unknown>;
    expect(f.next_dividend_within_days).toBe(14);
    expect(f.next_dividend_within_days_max).toBeUndefined();
  });

  it("omits both calendar fields when unset", () => {
    const filters = buildScreenerFilters(makeFilters({ peMin: 10 }));
    const f = filters[0] as Record<string, unknown>;
    expect(f.next_earnings_within_days).toBeUndefined();
    expect(f.next_dividend_within_days).toBeUndefined();
  });
});

// ── NL-translate reverse mapping (PLAN-0091) ───────────────────────────────────

describe("nlFiltersToFilterState", () => {
  it("maps a metric range row back to its FilterState min/max pair", () => {
    const fs = nlFiltersToFilterState([
      { metric: "pe_ratio", min_value: 5, max_value: 20 },
    ]);
    expect(fs.peMin).toBe(5);
    expect(fs.peMax).toBe(20);
  });

  it("maps multiple metrics + sector across several filter rows", () => {
    const fs = nlFiltersToFilterState([
      { metric: "market_capitalization", min_value: 10_000_000_000 },
      { metric: "dividend_yield", min_value: 0.02, sector: "Information Technology" },
    ]);
    expect(fs.marketCapMin).toBe(10_000_000_000);
    expect(fs.divYieldMin).toBe(0.02);
    expect(fs.sector).toBe("Information Technology");
  });

  it("maps IB-L5 intelligence named siblings (news + alert)", () => {
    const fs = nlFiltersToFilterState([
      { metric: "market_capitalization", news_count_7d_min: 5, has_active_alert: true },
    ]);
    expect(fs.newsCount7dMin).toBe(5);
    expect(fs.hasActiveAlert).toBe(true);
  });

  it("skips unknown metrics without throwing (forward-compatible)", () => {
    const fs = nlFiltersToFilterState([
      { metric: "some_future_metric_we_dont_know", min_value: 1 },
      { metric: "pe_ratio", max_value: 15 },
    ]);
    // Unknown dropped; known one still applied.
    expect(fs.peMax).toBe(15);
  });

  it("returns clean DEFAULT_FILTERS-based state for an empty filter list", () => {
    const fs = nlFiltersToFilterState([]);
    expect(fs.search).toBe("");
    expect(fs.capTier).toBe("ALL");
    expect(fs.peMin).toBeUndefined();
  });
});
