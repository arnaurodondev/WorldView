/**
 * features/screener/lib/filter-state.ts — Canonical screener filter state shape
 * + constants (GICS sectors, market-cap tiers, default form).
 *
 * WHY EXTRACTED (PLAN-0059 E-4): the type was previously co-located with the
 * 986-LOC ScreenerFilterBar. Saved-screens (PLAN-0051 Wave B Part 2), the URL
 * state migration (PLAN-0059 C-6 nuqs), and any future drill-down panels all
 * need the same shape — pulling it into a feature-local module gives them a
 * stable import surface that doesn't drag the entire FilterBar along.
 *
 * BACKEND METRIC NAMES (authoritative — see docs/services/market-data.md):
 * The frontend MUST use the exact metric names from the `metric_extractor.py`
 * truth column. The seed names in `screen_field_metadata` are NOT correct (see
 * docs/audits/2026-04-29-screener-metric-gap.md). Names referenced in the
 * field comments below:
 *   pe_ratio, pb_ratio, price_sales_ttm, dividend_yield,
 *   roe_ttm, profit_margin, operating_margin_ttm,
 *   quarterly_revenue_growth_yoy, quarterly_earnings_growth_yoy,
 *   market_capitalization, beta.
 */

/**
 * GICS sectors — 11 official sectors. Matches Bloomberg EQUITY SCREEN and
 * Finviz sector filter conventions.
 */
export const GICS_SECTORS = [
  "Information Technology",
  "Health Care",
  "Financials",
  "Consumer Discretionary",
  "Consumer Staples",
  "Communication Services",
  "Industrials",
  "Materials",
  "Real Estate",
  "Utilities",
  "Energy",
] as const;

/** CapTier — market cap filter tiers matching S9 screener backend expectations. */
export type CapTier = "ALL" | "LARGE" | "MID" | "SMALL";

export const CAP_TIERS: ReadonlyArray<{
  value: CapTier;
  label: string;
  description: string;
}> = [
  { value: "ALL", label: "All", description: "No market cap filter" },
  { value: "LARGE", label: "Large", description: "> $10B" },
  { value: "MID", label: "Mid", description: "$2B–$10B" },
  { value: "SMALL", label: "Small", description: "< $2B" },
];

/**
 * FilterState — full union of every filter control on the panel.
 *
 * Numeric ranges use `*Min`/`*Max` pairs; either side is optional so users can
 * specify "P/E < 20" without setting a min, etc. The empty string is also
 * tolerated in the UI (rendered → undefined when serialising the request).
 *
 * Three categories of fields are tagged inline with comments:
 *   SERVER_SIDE     — sent verbatim to S9 → S3 fundamentals/screen
 *   CLIENT_FILTER   — applied AFTER fetch on the returned ScreenerResult[]
 *                     (technical / signals)
 *   BACKEND_PENDING — input rendered but disabled in UI (gap documented in
 *                     audit)
 *
 * Keeping all three on the same FilterState shape keeps the parent integration
 * trivial (no second state object) and lets the user's saved screens (Part 2)
 * round-trip every filter even when some are not yet wired.
 */
export interface FilterState {
  // ── Existing top-row filters ─────────────────────────────────────────
  search: string;
  sector: string; // "" = all sectors
  capTier: CapTier;

  // ── Valuation (SERVER_SIDE) ─────────────────────────────────────────
  peMin?: number;
  peMax?: number; // pe_ratio
  pbMin?: number;
  pbMax?: number; // pb_ratio
  psMin?: number;
  psMax?: number; // price_sales_ttm
  divYieldMin?: number;
  divYieldMax?: number; // dividend_yield (decimal: 0.015 = 1.5%)

  // ── Profitability ───────────────────────────────────────────────────
  roeMin?: number;
  roeMax?: number; // roe_ttm (SERVER_SIDE)
  grossMarginMin?: number;
  grossMarginMax?: number; // BACKEND_PENDING (gross_profit/revenue not derived)
  netMarginMin?: number;
  netMarginMax?: number; // profit_margin (SERVER_SIDE)
  opMarginMin?: number;
  opMarginMax?: number; // operating_margin_ttm (SERVER_SIDE)

  // ── Growth (SERVER_SIDE) ────────────────────────────────────────────
  revGrowthMin?: number;
  revGrowthMax?: number; // quarterly_revenue_growth_yoy
  earningsGrowthMin?: number;
  earningsGrowthMax?: number; // quarterly_earnings_growth_yoy

  // ── Leverage (BACKEND_PENDING — both ratios un-derived; see audit) ──
  debtEquityMin?: number;
  debtEquityMax?: number;
  currentRatioMin?: number;
  currentRatioMax?: number;

  // ── Technical (CLIENT_FILTER unless noted) ──────────────────────────
  above50dMa?: boolean; // CLIENT_FILTER (no `50d_ma` field on response yet)
  rsiMin?: number; // CLIENT_FILTER
  rsiMax?: number; // CLIENT_FILTER
  volumeRatioMin?: number; // CLIENT_FILTER (1, 1.5, 2 — vs 30d avg)
  distFrom52wHighMax?: number; // CLIENT_FILTER (% — "within 5% of 52W high" → max=5)
  distFrom52wLowMin?: number; // CLIENT_FILTER (% — "at least X% above 52W low")

  // ── News & Signals (CLIENT_FILTER TODO — fields not on response) ────
  newsVelocity7dMin?: number; // CLIENT_FILTER TODO (S6 signals)
  controversyMin?: number; // CLIENT_FILTER TODO
  controversyMax?: number; // CLIENT_FILTER TODO
  recentEarningsDays?: 7 | 30; // CLIENT_FILTER TODO (S3 earnings calendar)
  insiderActivity?: "BUYING" | "SELLING" | "BOTH"; // CLIENT_FILTER TODO (S4 insider)
}

/** DEFAULT_FILTERS — used by the page initial state and the Reset button. */
export const DEFAULT_FILTERS: FilterState = {
  search: "",
  sector: "",
  capTier: "ALL",
};
