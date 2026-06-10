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

  // ── Market cap range (SERVER_SIDE) — complements the capTier tier filter ──
  // WHY separate from capTier: capTier maps to Large/Mid/Small buckets on the
  // backend. marketCapMin/Max let the user set exact USD thresholds (e.g. "$50B
  // only") which the tier enum cannot express. Both can be set simultaneously;
  // the backend AND-combines them.
  marketCapMin?: number; // market_capitalization in USD (e.g. 10_000_000_000 = $10B)
  marketCapMax?: number;

  // ── Valuation (SERVER_SIDE) ─────────────────────────────────────────
  peMin?: number;
  peMax?: number; // pe_ratio
  pbMin?: number;
  pbMax?: number; // pb_ratio
  psMin?: number;
  psMax?: number; // price_sales_ttm
  divYieldMin?: number;
  divYieldMax?: number; // dividend_yield (decimal: 0.015 = 1.5%)
  forwardPeMin?: number;
  forwardPeMax?: number; // forward_pe (next-twelve-months EPS estimate)

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
  // ── 30-day average volume, ABSOLUTE shares (SERVER_SIDE — Round 2) ──
  // WHY separate from volumeRatioMin: the ratio select is a relative,
  // client-side spike detector ("trading at 2× normal volume"). These are
  // absolute liquidity bounds ("avg ≥ 1M shares/day") that S3 filters
  // server-side via the per-filter `avg_volume_30d_min/max` named fields on
  // ScreenFilterRequest (instrument_fundamentals_snapshot.avg_volume_30d) —
  // a Round-1 gap: the backend supported this but the UI never exposed it.
  avgVolume30dMin?: number; // avg_volume_30d_min (SERVER_SIDE, shares)
  avgVolume30dMax?: number; // avg_volume_30d_max (SERVER_SIDE, shares)
  distFrom52wHighMax?: number; // CLIENT_FILTER (% — "within 5% of 52W high" → max=5)
  distFrom52wLowMin?: number; // CLIENT_FILTER (% — "at least X% above 52W low")

  // ── Performance / Returns (SERVER_SIDE — IB-L3) ──────────────────────
  // WHY these 8 fields: backend computes them nightly via ComputedMetricsBackfillWorker
  // and stores them in instrument_fundamentals_snapshot. All stored as decimals
  // (0.124 = +12.4%); backend filters expect the same decimal scale.
  dist52wHighPctMin?: number; // dist_from_52w_high_pct (SERVER_SIDE)
  dist52wHighPctMax?: number;
  dist52wLowPctMin?: number;  // dist_from_52w_low_pct (SERVER_SIDE)
  dist52wLowPctMax?: number;
  return1mMin?: number;       // return_1m (SERVER_SIDE)
  return1mMax?: number;
  return3mMin?: number;       // return_3m (SERVER_SIDE)
  return3mMax?: number;
  return6mMin?: number;       // return_6m (SERVER_SIDE)
  return6mMax?: number;
  returnYtdMin?: number;      // return_ytd (SERVER_SIDE)
  returnYtdMax?: number;
  return1yMin?: number;       // return_1y (SERVER_SIDE)
  return1yMax?: number;
  return3yMin?: number;       // return_3y (SERVER_SIDE)
  return3yMax?: number;

  // ── Analyst / Insider / Ownership (SERVER_SIDE — IB-L4) ─────────────
  // WHY these 5 server-side fields: L-4a shipped 4 analyst columns (target price,
  // consensus rating, institutional ownership pct, short percent) and L-4b shipped
  // insider_net_buy_90d. All are stored in instrument_fundamentals_snapshot.
  analystTargetPriceMin?: number; // analyst_target_price (SERVER_SIDE, absolute USD)
  analystTargetPriceMax?: number;
  analystConsensusMin?: number;   // analyst_consensus_rating (SERVER_SIDE, 1–5 scale)
  analystConsensusMax?: number;
  insiderNetBuy90dMin?: number;   // insider_net_buy_90d (SERVER_SIDE, USD; null ≠ 0)
  insiderNetBuy90dMax?: number;
  instOwnPctMin?: number;         // institutional_ownership_pct (SERVER_SIDE, decimal)
  instOwnPctMax?: number;
  shortPctMin?: number;           // short_percent (SERVER_SIDE, decimal)
  shortPctMax?: number;

  // ── News & Signals (CLIENT_FILTER TODO — fields not on response) ────
  newsVelocity7dMin?: number; // CLIENT_FILTER TODO (S6 signals)
  controversyMin?: number; // CLIENT_FILTER TODO
  controversyMax?: number; // CLIENT_FILTER TODO
  recentEarningsDays?: 7 | 30; // CLIENT_FILTER TODO (S3 earnings calendar)
  insiderActivity?: "BUYING" | "SELLING" | "BOTH"; // CLIENT_FILTER TODO (S4 insider)

  // ── Intelligence rollup (SERVER_SIDE — IB-L5) ───────────────────────
  // WHY these 7 fields: the S7→S3 nightly rollup (L-5b worker) populates
  // instrument_fundamentals_snapshot with intelligence signals from S6/S7/S8/S10.
  // Backend metric names match the exact column names in that table.
  newsCount7dMin?: number;              // news_count_7d ≥ (INTEGER, count of articles last 7d)
  newsCount7dMax?: number;
  llmRelevance7dMin?: number;           // llm_relevance_7d_max (FLOAT 0–1, max per-article score)
  llmRelevance7dMax?: number;
  displayRelevance7dMin?: number;       // display_relevance_7d_weighted (FLOAT 0–1, weighted avg)
  displayRelevance7dMax?: number;
  contradictionsMin?: number;           // recent_contradiction_count (INTEGER, KG contradictions)
  contradictionsMax?: number;
  hasAiBrief?: boolean;                 // has_ai_brief (BOOLEAN, TRUE = brief exists in S8)
  hasActiveAlert?: boolean;             // has_active_alert (BOOLEAN, TRUE = live alert in S10)
}

/** DEFAULT_FILTERS — used by the page initial state and the Reset button. */
export const DEFAULT_FILTERS: FilterState = {
  search: "",
  sector: "",
  capTier: "ALL",
};
