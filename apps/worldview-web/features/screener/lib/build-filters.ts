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

  // Attach sector restriction to the first filter (S3 applies it globally).
  if (f.sector && filters.length > 0) {
    filters[0] = { ...filters[0], sector: f.sector };
  }

  // Backend rejects empty filter lists (min_length=1).
  if (filters.length === 0) {
    filters.push({
      metric: "market_capitalization",
      min_value: 0,
      ...(f.sector ? { sector: f.sector } : {}),
    });
  }

  // WHY always include daily_return + pe_ratio: without these, the backend
  // omits those columns from result rows when no filter constraint is set.
  if (!filters.some((f) => f.metric === "daily_return")) {
    filters.push({ metric: "daily_return", min_value: -1, max_value: 1 });
  }
  if (!filters.some((f) => f.metric === "pe_ratio")) {
    filters.push({ metric: "pe_ratio", min_value: -9999, max_value: 9999 });
  }

  return filters;
}
