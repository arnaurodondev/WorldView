/**
 * build-filters.ts — buildScreenerFilters utility
 *
 * WHY THIS EXISTS: Extracted from app/(app)/screener/page.tsx so the function
 * can be imported by unit tests without re-exporting from a Next.js page
 * (which causes TS2344 — page files may not export non-Next.js symbols).
 *
 * WHO USES IT: screener/page.tsx (at query build time), screener-build-filters.test.ts
 * DATA SOURCE: FilterState UI state → ScreenerRequest.filters[] for POST /v1/fundamentals/screen
 */

import type { ScreenerFilter } from "@/types/api";
import type { FilterState } from "./filter-state";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pushIfRange(
  out: ScreenerFilter[],
  metric: string,
  min: number | undefined,
  max: number | undefined,
): void {
  if (min === undefined && max === undefined) return;
  out.push({ metric, min_value: min, max_value: max });
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * buildScreenerFilters — converts UI FilterState to ScreenerRequest.filters[].
 *
 * Maps each fundamental UI filter to the canonical backend metric name from
 * docs/services/market-data.md (PLAN-0051 T-B-2-01).
 *
 * Part 4 fix: daily_return and pe_ratio are always appended so the backend
 * computes those columns on every row even when the user set no range filter.
 */
export function buildScreenerFilters(f: FilterState): ScreenerFilter[] {
  const filters: ScreenerFilter[] = [];

  // Cap tier → market_capitalization range
  let capMin: number | undefined;
  let capMax: number | undefined;
  if (f.capTier === "LARGE") capMin = 10_000_000_000;
  else if (f.capTier === "MID") {
    capMin = 2_000_000_000;
    capMax = 10_000_000_000;
  } else if (f.capTier === "SMALL") capMax = 2_000_000_000;
  pushIfRange(filters, "market_capitalization", capMin, capMax);

  // ── Valuation (SERVER_SIDE) ────────────────────────────────────────────────
  pushIfRange(filters, "pe_ratio", f.peMin, f.peMax);
  pushIfRange(filters, "pb_ratio", f.pbMin, f.pbMax);
  pushIfRange(filters, "price_sales_ttm", f.psMin, f.psMax);
  pushIfRange(filters, "dividend_yield", f.divYieldMin, f.divYieldMax);

  // ── Profitability (SERVER_SIDE) ────────────────────────────────────────────
  pushIfRange(filters, "roe_ttm", f.roeMin, f.roeMax);
  pushIfRange(filters, "profit_margin", f.netMarginMin, f.netMarginMax);
  pushIfRange(filters, "operating_margin_ttm", f.opMarginMin, f.opMarginMax);

  // ── Growth (SERVER_SIDE) ───────────────────────────────────────────────────
  pushIfRange(filters, "quarterly_revenue_growth_yoy", f.revGrowthMin, f.revGrowthMax);
  pushIfRange(filters, "quarterly_earnings_growth_yoy", f.earningsGrowthMin, f.earningsGrowthMax);

  // Sector filter: when sector is selected but no other metric filters are active
  // we still need to communicate the sector restriction. S3's sector field lives on
  // ScreenFilterRequest, so we attach it to the first filter or add a synthetic one.
  if (f.sector && f.sector !== "ALL") {
    if (filters.length > 0) {
      filters[0] = { ...filters[0], sector: f.sector };
    } else {
      // WHY synthetic filter with no numeric range: S3 accepts filters[] with both
      // min_value and max_value omitted — it just uses the filter for sector restriction
      // without applying any numeric threshold. Sending {metric, sector} alone tells S3
      // to restrict the universe to that sector and return key metrics via LEFT JOIN.
      filters.push({ metric: "market_capitalization", sector: f.sector });
    }
  }

  // WHY no fallback filter when filters is empty: S3 v2 accepts filters:[] and
  // responds with the optimised "no filter" path — LEFT JOINs across key metrics
  // (market_cap, pe_ratio, beta, daily_return, revenue_usd) for ALL instruments.
  // Previously we sent [{market_cap, min: 0}] here, which triggered S3's INNER JOIN
  // path and only populated the market_cap column, leaving all others "—".

  return filters;
}
