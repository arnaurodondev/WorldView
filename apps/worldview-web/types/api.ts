/**
 * types/api.ts — Domain types for all S9 API responses
 *
 * WHY THIS EXISTS: Centralises TypeScript types for every S9 endpoint response.
 * Components import from here instead of redefining shapes inline, ensuring
 * a single source of truth. When S9 response shapes change, only this file
 * and the gateway client need updating.
 *
 * WHO USES IT: lib/gateway.ts (client methods), all feature components,
 * useQuery hooks throughout the app.
 *
 * DATA SOURCE: docs/specs/0028-worldview-web-frontend.md §6.2
 * DESIGN REFERENCE: All canvas states reference these types.
 */

// ── Authentication ─────────────────────────────────────────────────────────

export interface AuthTokens {
  access_token: string;
  token_type: "bearer";
  expires_in: number; // seconds — typically 900 (15 min)
}

export interface UserProfile {
  user_id: string;
  tenant_id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

export interface AuthCallbackResponse {
  access_token: string;
  expires_in: number;
  user: UserProfile;
}

export interface WsTokenResponse {
  token: string;
  expires_in: 30; // always 30 seconds — short-lived for log safety
}

// ── Instruments / Market Data ──────────────────────────────────────────────

export interface Instrument {
  instrument_id: string;
  entity_id: string;    // WHY separate: entity_id ≠ instrument_id (ADR-F-12)
  ticker: string;       // e.g., "AAPL"
  name: string;         // e.g., "Apple Inc."
  exchange: string;     // e.g., "NASDAQ"
  currency: string;     // e.g., "USD"
  gics_sector: string | null;
  gics_industry: string | null;
  isin: string | null;
  country: string | null;
  // WHY description optional (not required): older instruments populated before the
  // company-profile ingestion wave may not have a description in company_profiles.
  // The UI handles null gracefully (shows nothing). EODHD "General.Description" field.
  description: string | null;
}

export interface OHLCVBar {
  timestamp: string; // ISO 8601 UTC
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OHLCVResponse {
  instrument_id: string;
  ticker: string;
  timeframe: string; // "1D", "1H", "5M"
  bars: OHLCVBar[];
}

export interface Quote {
  instrument_id: string;
  ticker: string;
  price: number;
  change: number;       // absolute change from previous close
  change_pct: number;   // percentage change
  timestamp: string;    // ISO 8601 UTC
  volume: number | null;
  // WHY optional: freshness fields added in PLAN-0036 Wave 1 — backward compatible
  // during rollout. Once all S9 quote routes call the new PriceSnapshot endpoint,
  // these will be populated on every response.
  freshness_status?: "live" | "recent" | "delayed" | "stale" | "unavailable";
  source?: "fresh_quote" | "bulk_quote" | "intraday_5m_close" |
           "intraday_1h_close" | "daily_close" | "stale_snapshot" | "unavailable";
  data_as_of?: string;          // ISO 8601 UTC — when the price was valid (may differ from timestamp)
  stale_reason?: string | null; // human-readable reason e.g. "No quote in last 15 min"
  refresh_available?: boolean;  // whether a manual refresh can be triggered
  refresh_cooldown_remaining_sec?: number; // seconds until next manual refresh is allowed
}

/** Response for POST /v1/instruments/{id}/refresh-price */
export interface RefreshPriceResponse {
  instrument_id: string;
  status: "accepted" | "cooldown";
  cooldown_remaining_sec?: number; // populated when status = "cooldown"
  message: string;
}

export interface BatchQuoteResponse {
  quotes: Record<string, Quote>; // keyed by instrument_id
}

// ── Fundamentals ───────────────────────────────────────────────────────────

export interface Fundamentals {
  instrument_id: string;
  ticker: string;
  name: string;
  // Valuation
  market_cap: number | null;
  pe_ratio: number | null;
  forward_pe: number | null;
  price_to_book: number | null;
  price_to_sales: number | null;
  ev_to_ebitda: number | null;
  // Profitability
  gross_margin: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  roe: number | null;
  roa: number | null;
  // Growth
  revenue_growth_yoy: number | null;
  earnings_growth_yoy: number | null;
  // Dividends
  dividend_yield: number | null;
  payout_ratio: number | null;
  // Balance sheet
  debt_to_equity: number | null;
  current_ratio: number | null;
  quick_ratio: number | null;
  // 52-week
  week_52_high: number | null;
  week_52_low: number | null;
  // Daily
  daily_return: number | null;
  updated_at: string; // ISO 8601 UTC
}

/**
 * FundamentalsSnapshot — flat one-row snapshot of 10 derived metrics.
 *
 * WHY SEPARATE FROM Fundamentals: The main Fundamentals type is assembled by
 * S9 from EODHD highlights/technicals JSONB sections (market cap, P/E, margins).
 * This snapshot type comes from the instrument_fundamentals_snapshot table which
 * is populated by the backfill script — it pre-computes derived metrics (FCF,
 * interest coverage, net debt/EBITDA) that would require multi-section joins at
 * query time.  Keeping them separate avoids mutating the existing Fundamentals
 * type (forward-compat rule R11) and lets the two endpoints evolve independently.
 *
 * All fields are nullable: NULL → "—" in the UI (data not yet backfilled or
 * genuinely unavailable for this instrument — e.g. ETFs with no cash flow statements).
 *
 * Source: S9 GET /v1/fundamentals/{id}/snapshot → S3 /api/v1/fundamentals/{id}/snapshot
 * PLAN-0050 Wave D (T-D-4-04)
 */
export interface FundamentalsSnapshot {
  instrument_id: string;
  // EPS trailing twelve months from EODHD Highlights
  eps_ttm: number | null;
  // Market beta (52-week vs S&P 500) from EODHD Technicals
  beta: number | null;
  // 30-day average daily volume from EODHD Technicals/ShareStatistics
  avg_volume_30d: number | null;
  // Cash flow statement (most recent annual)
  operating_cash_flow: number | null;
  capex: number | null;
  // Derived: free_cash_flow = operating_cash_flow - |capex|
  free_cash_flow: number | null;
  // Derived: fcf_margin = free_cash_flow / revenue (null if revenue = 0)
  fcf_margin: number | null;
  // Derived: interest_coverage = ebit / interest_expense
  interest_coverage: number | null;
  // Derived: net_debt_to_ebitda = (total_debt - cash) / ebitda
  net_debt_to_ebitda: number | null;
  // Credit rating string (e.g. "A+", "BBB-") — always null until a credit data provider is integrated
  credit_rating: string | null;
  // ISO 8601 UTC timestamp of the last backfill run that produced this row
  updated_at: string | null;
}

// ── Fundamentals Section Records (S3 raw format) ────────────────────────────
//
// WHY separate from Fundamentals: The main Fundamentals type represents the
// flattened aggregate snapshot (market cap, P/E, margins). These Section types
// represent the raw time-series records from S3's fundamentals_data table —
// each record has a `section` tag and a `data` dict of arbitrary key-value pairs
// specific to that section. The frontend casts `data` to a typed interface below.

export interface FundamentalsRecord {
  id: string;
  security_id: string;
  section: string;          // e.g., "technicals_snapshot", "earnings_history"
  period_end: string;       // ISO 8601 date — record's reporting date
  period_type: "ANNUAL" | "QUARTERLY" | "SNAPSHOT";
  data: Record<string, unknown>; // section-specific fields; cast with typed interfaces below
  source: string;
  ingested_at: string;      // ISO 8601 UTC
}

export interface FundamentalsSectionResponse {
  security_id: string;
  records: FundamentalsRecord[];
}

// ── Fundamentals Timeseries ─────────────────────────────────────────────────
//
// WHY separate from FundamentalsRecord: Timeseries returns a flat array of
// (date, value) pairs for a single metric — used by FundamentalSparkline.
// Different S3 endpoint (GET /v1/fundamentals/timeseries) returning a single-metric
// time series rather than a multi-field snapshot record.

export interface TimeseriesDataPoint {
  as_of_date: string;       // ISO 8601 date
  value_numeric: number | null;
  value_text: string | null;
  period_type: string;      // "ANNUAL" | "QUARTERLY" | "SNAPSHOT"
}

export interface FundamentalsTimeseriesResponse {
  instrument_id: string;
  metric: string;           // e.g., "pe_ratio", "revenue", "gross_margin"
  data: TimeseriesDataPoint[];
}

// ── Typed section data shapes (extracted from FundamentalsRecord.data) ──────
//
// WHY typed (not Record<string, unknown>): S3 section data fields are well-known
// from the EODHD API schema. Typing prevents runtime crashes from misspelled fields.
// All fields are nullable — newly-listed stocks or missing EODHD data can yield
// null for any field.

export interface TechnicalsData {
  beta: number | null;
  "52_week_high": number | null;
  "52_week_low": number | null;
  "50_day_ma": number | null;
  "200_day_ma": number | null;
  shares_short: number | null;
  short_ratio: number | null;
  short_percent: number | null;
}

export interface ShareStatisticsData {
  shares_outstanding: number | null;
  shares_float: number | null;
  percent_insiders: number | null;
  percent_institutions: number | null;
}

export interface InsiderTransaction {
  date: string;
  owner_name: string;
  transaction_type: string; // "Buy", "Sale", "Option Exercise", etc.
  shares: number | null;
  value: number | null;     // USD
}

export interface EarningsRecord {
  date: string;
  eps_actual: number | null;
  eps_estimate: number | null;
  revenue_actual: number | null;
  revenue_estimate: number | null;
  surprise_percent: number | null; // positive = beat, negative = miss
}

export interface AnalystConsensusData {
  buy: number | null;
  hold: number | null;
  sell: number | null;
  strong_buy: number | null;
  strong_sell: number | null;
  target_price: number | null;
  target_price_high: number | null;
  target_price_low: number | null;
  target_price_median: number | null;
  number_of_analysts: number | null;
}

// ── Company Overview (composed endpoint) ──────────────────────────────────

export interface CompanyOverview {
  instrument: Instrument;
  quote: Quote | null;
  fundamentals: Fundamentals | null;
  ohlcv: OHLCVResponse | null; // last 30 days 1D bars for the mini chart
}

// ── Knowledge Graph ────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;         // entity_id
  label: string;      // entity name
  type: string;       // "company", "person", "event", "topic"
  size?: number;      // relative importance score for sigma.js node sizing
  x?: number;         // layout position (set by sigma.js)
  y?: number;
}

export interface GraphEdge {
  id: string;
  source: string;     // entity_id
  target: string;     // entity_id
  label: string;      // relationship type (e.g., "CEO_OF", "COMPETES_WITH")
  weight: number;     // confidence / strength [0, 1]
}

export interface EntityGraph {
  entity_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Contradiction {
  contradiction_id: string;
  entity_id: string;
  claim_a: string;
  claim_b: string;
  source_a: string;
  source_b: string;
  detected_at: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
}

export interface ContradictionsResponse {
  entity_id: string;
  contradictions: Contradiction[];
}

// ── News ───────────────────────────────────────────────────────────────────

export interface Article {
  article_id: string;
  title: string;
  url: string;
  source: string;
  published_at: string; // ISO 8601 UTC
  summary: string | null;
  entity_ids: string[];
  tickers: string[];
  // Scoring fields (PRD-0026 — may be null on older articles)
  display_relevance_score: number | null; // 0.0–1.0
  market_impact_score: number | null;
  sentiment: "positive" | "negative" | "neutral" | null;
  impact_window_t0: number | null; // 1-day price impact
  impact_window_t1: number | null; // 2-day
  impact_window_t2: number | null; // 3-day
  impact_window_t5: number | null; // 5-day
  // WHY optional: older API responses may omit this field; undefined → treat as STANDARD.
  // LIGHT = low-relevance/low-signal article (de-emphasised in UI at 60% opacity).
  // HIGH = top-ranked article (may receive visual boost in future waves).
  routing_tier?: "LIGHT" | "STANDARD" | "HIGH";
}

export interface NewsResponse {
  articles: Article[];
  total: number;
  offset: number;
  limit: number;
}

// ── Ranked News (PRD-0026) ─────────────────────────────────────────────────
//
// WHY separate from Article: S6's ranked news endpoint returns a richer
// structure with multi-window price impact scores and separate source fields.
// The S5 "relevant news" endpoint (getRelevantNews) still returns the old
// Article shape, so both interfaces coexist in the codebase.

/**
 * Per-window price impact scores after an article's publication.
 * Each value is 0.0–1.0, measuring how much the article moved the entity's
 * stock price in the N trading days after publication.
 * null = not yet computed (article too recent, or OHLCV data unavailable).
 */
export interface ImpactWindows {
  day_t0: number | null;  // Publication-day OHLCV price impact
  day_t1: number | null;  // Following-day impact (T+1)
  day_t2: number | null;  // 2-day cumulative impact (T+2)
  day_t5: number | null;  // 5-trading-day cumulative impact (T+5)
}

/**
 * A news article returned by S6's ranked news endpoints (PRD-0026 §6.2).
 * display_relevance_score is the weighted composite signal used for ordering:
 *   full-signal:   0.50 * market_impact + 0.40 * llm_relevance + 0.10 * routing
 *   market-only:   0.70 * market_impact + 0.30 * routing
 *   llm-only:      0.60 * llm_relevance + 0.40 * routing
 *   routing-only:  0.40 * routing  (fallback when no ML signals available)
 */
export interface RankedArticle {
  article_id: string;
  title: string | null;
  url: string | null;
  published_at: string | null;            // ISO-8601 UTC
  source_type: string | null;             // e.g. "eodhd_news" (technical identifier)
  source_name: string | null;             // e.g. "EODHD" (human-readable display name)
  routing_tier: string | null;            // "LIGHT" | "MEDIUM" | "DEEP"
  routing_score: number | null;           // 0.0–1.0 composite routing confidence
  market_impact_score: number | null;     // null if no price windows computed yet
  llm_relevance_score: number | null;     // null for LIGHT tier (skipped) or unscored
  display_relevance_score: number;        // always 0.0–1.0; used for UI sort order
  primary_entity_id: string | null;       // top entity for this article (global feed only)
  primary_entity_symbol: string | null;   // ticker of top entity (global feed only)
  impact_windows: ImpactWindows | null;   // null when OHLCV data not yet available
  // PLAN-0050 Wave E: article-level sentiment + aggregated impact score.
  // sentiment: categorical signal from ArticleRelevanceScoringWorker.
  //   null for LIGHT-tier articles (skipped) or articles not yet processed.
  //   "positive" | "negative" | "neutral" | "mixed"
  // impact_score: convenience copy of MAX(day_t0, day_t1) from price-impact windows.
  //   null until PriceImpactLabellingWorker computes windows (< 25h old articles).
  sentiment: "positive" | "negative" | "neutral" | "mixed" | null;
  impact_score: number | null;            // 0.0–1.0; null until price windows computed
}

/**
 * Response from GET /v1/news/top and GET /v1/news/entity/{id} (PRD-0026 §6.2).
 * Unlike the legacy NewsResponse, there are no offset/limit fields —
 * clients track pagination state locally using the total count.
 */
export interface RankedNewsResponse {
  articles: RankedArticle[];
  total: number;
}

/** Query params for GET /v1/news/top (PRD-0026 §6.2 F-25) */
export interface TopNewsParams {
  hours?: number;                         // 1–168, default 24
  limit?: number;                         // 1–100, default 20
  offset?: number;
  min_display_score?: number;             // filter: minimum composite score 0.0–1.0
  routing_tier?: 'LIGHT' | 'MEDIUM' | 'DEEP';
}

/** Query params for GET /v1/news/entity/{id} (PRD-0026 §6.2 F-26) */
export interface EntityNewsParams {
  start_date?: string;                    // ISO-8601 UTC
  end_date?: string;                      // ISO-8601 UTC
  order_by?: 'display_relevance_score' | 'published_at';
  limit?: number;
  offset?: number;
}

// ── Screener ───────────────────────────────────────────────────────────────

export interface ScreenerFieldOption {
  value: string;
  label: string;
}

export interface ScreenerField {
  name: string;
  label: string;
  type: "number" | "string" | "select";
  operators: string[]; // "gt", "lt", "eq", "in", etc.
  options?: ScreenerFieldOption[]; // for select type
  description: string | null;
}

export interface ScreenerFilter {
  field: string;
  operator: string;
  value: number | string | string[];
}

export interface ScreenerRequest {
  filters: ScreenerFilter[];
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;  // default 20, max 100
  offset?: number; // default 0
}

export interface ScreenerResult {
  instrument_id: string;
  entity_id: string;
  ticker: string;
  name: string;
  exchange: string;
  gics_sector: string | null;
  // Core screener metrics — always returned by POST /v1/fundamentals/screen
  market_cap: number | null;
  pe_ratio: number | null;
  daily_return: number | null;
  market_impact_score: number | null; // PRD-0020 signal score
  // Extended fields — returned when available; backend may omit if not computed
  // WHY optional (not null): older screener payloads pre-dating extended fields won't
  // include these keys at all. Optional vs null lets us distinguish "not returned" from
  // "returned as null" — relevant for the "—" vs "0" display decision.
  current_price?: number | null;       // live quote price (from quote enrichment)
  revenue?: number | null;             // trailing 12-month revenue (USD)
  beta?: number | null;                // market beta vs S&P 500
  forward_pe?: number | null;          // forward P/E ratio (next-twelve-months EPS)
  dividend_yield?: number | null;      // annual dividend yield (decimal, e.g. 0.015 = 1.5%)
  revenue_growth_yoy?: number | null;  // year-over-year revenue growth (decimal)
  roe?: number | null;                 // return on equity (decimal)
  [key: string]: unknown; // dynamic fields depending on screener config
}

export interface ScreenerResponse {
  results: ScreenerResult[];
  total: number;
  offset: number;
  limit: number;
}

// ── Portfolio ──────────────────────────────────────────────────────────────

export interface Portfolio {
  portfolio_id: string;
  name: string;
  currency: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
  // PLAN-0046 Wave 3 / T-46-3-04 — kind discriminator from S1.
  //   "manual"    : user-created, transactions entered by hand
  //   "brokerage" : created during a SnapTrade brokerage connection flow
  //   "root"      : auto-provisioned aggregate ("All Accounts") — read-only,
  //                 cannot be deleted, holds no positions of its own.
  // The frontend uses this to (a) sort the root entry first in the selector,
  // (b) show an "ALL" badge, and (c) hide/disable the delete button.
  // Optional only because older S9 builds may not yet emit it; once the
  // gateway response is updated this can become required.
  kind?: "manual" | "brokerage" | "root";
}

export interface Holding {
  holding_id: string;
  portfolio_id: string;
  instrument_id: string;
  entity_id: string;
  ticker: string;
  name: string;
  quantity: number;
  average_cost: number; // per share, in portfolio currency
  current_price?: number | null; // enriched from quotes, not stored
  unrealised_pnl?: number | null; // computed: (current_price - avg_cost) * qty
  unrealised_pnl_pct?: number | null;
  portfolio_weight?: number | null; // % of total portfolio value
}

export interface Transaction {
  transaction_id: string;
  portfolio_id: string;
  instrument_id: string;
  ticker: string;
  type: "BUY" | "SELL" | "DIVIDEND";
  quantity: number;
  price: number;
  fee: number;
  // PLAN-0046 / BP-263: broker-reported cash amount, primarily used to surface
  // DIVIDEND values. SnapTrade reports dividends as units≈0, price≈0, with the
  // payment in `amount`. For BUY/SELL `amount` is informational; the table
  // computes total = quantity * price for those types.
  // null = historical row pre-dating the column, OR a row where the broker
  // didn't supply this field (legitimately absent — render gracefully).
  amount: number | null;
  currency: string;
  executed_at: string; // ISO 8601 UTC
  notes: string | null;
}

export interface TransactionRequest {
  portfolio_id: string;
  instrument_id: string;
  type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fee?: number;
  executed_at?: string;
  notes?: string;
}

export interface HoldingsResponse {
  portfolio_id: string;
  holdings: Holding[];
  total_value: number | null;
  total_cost: number | null;
  total_unrealised_pnl: number | null;
  total_unrealised_pnl_pct: number | null;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  total: number;
  offset: number;
  limit: number;
}

// ── Portfolio analytics (PLAN-0046 Wave 5) ────────────────────────────────

/**
 * One point on the equity curve. S1 serialises Decimal fields as 8-dp
 * strings; the gateway parses them to numbers so chart components can
 * arithmetic on them directly without parseFloat-at-render-time.
 */
export interface ValueHistoryPoint {
  date: string;       // YYYY-MM-DD
  value: number;
  cost_basis: number;
  cash: number;
  /**
   * F-501 (QA iter-5): per-snapshot data-quality flag mirrored from the S1
   * ``portfolio_value_snapshots.data_quality`` column.
   *
   * - ``"ok"``: every holding had a fresh close on this snapshot's date.
   * - ``"partial_prices"``: at least one holding fell back to a stale close
   *   (lookback) or to cost basis. The equity-curve tooltip renders a small
   *   "Partial prices" caption on those points so the user understands this
   *   point is an honest estimate, not a clean-room valuation.
   *
   * Optional in the type because older S1 builds may omit it; the gateway
   * defaults to ``"ok"`` so consumers can compare strictly.
   */
  data_quality?: string;
}

/**
 * F-009 (QA iter-2): empty-state hint payload.
 *
 * ``last_snapshot_at`` — most recent snapshot in the FILTERED window (not
 * across all time). When the window is empty this is null.
 * ``next_scheduled_run_utc`` — full ISO-8601 timestamp of the next 21:30 UTC
 * snapshot wake-up. The chart's empty-state caption renders this as "Next
 * snapshot scheduled for YYYY-MM-DD HH:MM UTC".
 *
 * Both fields are independently nullable so older S1 builds that don't yet
 * populate them keep parsing.
 */
export interface ValueHistoryMetadata {
  last_snapshot_at: string | null;
  next_scheduled_run_utc: string | null;
}

export interface ValueHistoryResponse {
  points: ValueHistoryPoint[];
  // Optional on the wire — older gateways omit it; the chart falls back to
  // the previous static empty-state message when undefined.
  metadata?: ValueHistoryMetadata;
}

/**
 * Current invested / cash / leverage breakdown. ``*_pct`` fields are
 * fractions in [0, ~1] (NOT percent). Frontend multiplies by 100 for
 * display per the rest of the codebase convention.
 */
export interface ExposureResponse {
  invested: number;
  cash: number;
  gross_exposure_pct: number;
  net_exposure_pct: number;
  leverage: number;
  // F-016 (QA 2026-04-28): when the price client could not fetch a live
  // quote for one or more holdings, the use case falls back to
  // ``average_cost`` and sets this flag so the UI can render a
  // "Prices stale" badge above the gross-exposure number.
  // ``prices_as_of`` is reserved for v2 (currently always null on the wire).
  prices_stale?: boolean;
  prices_as_of?: string | null;
}

/**
 * Risk metrics from S9 composition endpoint.
 *
 * Every numeric field is independently nullable — ``null`` means the
 * metric is undefined for the given series (insufficient history,
 * volatility 0, no SPY data, etc.). Frontend renders ``null`` as "—".
 */
export interface RiskMetricsResponse {
  portfolio_id: string;
  lookback_days: number;
  drawdown_max: number | null;
  drawdown_current: number | null;
  volatility_annualized: number | null;
  sharpe: number | null;
  sortino: number | null;
  beta_vs_spy: number | null;
  n_returns: number;
  // F-014 / F-015 (QA 2026-04-28): context fields so the UI can render
  // a meaningful hint when metrics are null. ``as_of`` is the UTC ISO-8601
  // computation timestamp; ``lookback_window`` reports the actual
  // ``from``/``to`` dates the gateway used.
  // ``data_quality.status`` discriminates the three possible reasons a
  // metric might be null:
  //   "ok"                      — enough data; metrics are populated
  //   "insufficient_data"       — fewer than ~10 daily returns
  //   "benchmark_unavailable"   — SPY OHLCV missing → only beta is null
  as_of?: string;
  lookback_window?: { from: string; to: string };
  data_quality?: {
    // F-209 (QA iter-2): added "data_anomaly_detected" — gateway flags the
    // F-201 wipe pattern (a sudden zero in the value series) so the strip
    // can suppress misleading -100% drawdown / -3.4 Sharpe values.
    status:
      | "ok"
      | "insufficient_data"
      | "benchmark_unavailable"
      | "data_anomaly_detected";
    n_returns: number;
    lookback_days: number;
  };
}

// ── Realized P&L (PLAN-0051 T-A-1-04 / T-A-1-05) ──────────────────────────

/**
 * One realized-P&L line item, one per closed lot (FIFO).
 *
 * WHY a flat structure (not nested by instrument): the backend already
 * computes the per-instrument breakdown server-side, so the frontend can
 * simply render the array. Grouping client-side would force the tooltip
 * component to re-aggregate on every tile-hover render.
 */
export interface RealizedPnLBreakdownItem {
  instrument_id: string;
  ticker: string;
  /** Sum of FIFO realized P&L across all SELL fills against this instrument. */
  realized: number;
  /** SELL count contributing to this row — useful for "X lots realized" UX. */
  count: number;
}

/**
 * GET /v1/portfolios/{portfolio_id}/realized-pnl response.
 *
 * WHY long_term / short_term split: holding period > 365 days qualifies for
 * long-term capital-gains tax treatment in most jurisdictions. Traders use
 * this split to estimate after-tax realized P&L without a manual lot-by-lot
 * audit. The backend computes holding period at SELL time using the FIFO lot
 * acquired_at — the frontend only renders.
 */
export interface RealizedPnLResponse {
  portfolio_id: string;
  /** Inclusive lower bound applied to SELL.executed_at; "YYYY-MM-DD". */
  from: string;
  /** Inclusive upper bound applied to SELL.executed_at; "YYYY-MM-DD". */
  to: string;
  /** Sum of all realized P&L within [from, to]. */
  total_realized: number;
  /** Subset of `total_realized` from lots held > 365 days at sale time. */
  realized_long_term: number;
  /** Subset of `total_realized` from lots held ≤ 365 days at sale time. */
  realized_short_term: number;
  /** Number of SELL transactions that contributed to the total. */
  count: number;
  /** Per-instrument breakdown (newest-first by `realized` desc). */
  breakdown_by_instrument: RealizedPnLBreakdownItem[];
  /** Currency of the totals (matches portfolio.currency). */
  currency: string;
}

// ── Watchlist ──────────────────────────────────────────────────────────────

export interface WatchlistMember {
  entity_id: string;
  instrument_id: string | null;
  ticker: string | null;
  name: string;
  added_at: string;
  // F-010 (QA 2026-04-28): "resolved" when the local instruments cache
  // had a match at add-time, "pending" when not. The frontend renders
  // a small "resolving…" badge for pending rows.
  resolution?: "resolved" | "pending";
}

export interface Watchlist {
  watchlist_id: string;
  name: string;
  owner_id: string;
  members: WatchlistMember[];
  member_count: number;
  created_at: string;
  updated_at: string;
}

// ── Watchlist insights (PLAN-0050 Wave B / T-B-2-01) ──────────────────────────
//
// Composite payload returned by GET /v1/watchlists/{id}/insights — the
// WatchlistMoversWidget consumes this in lieu of fanning out 5 separate
// queries client-side. Every numeric field is nullable because the gateway's
// per-member sub-calls are best-effort (a flaky news service must not break
// the dashboard's primary movers list).

/** One member-level row in the insights payload — superset of the prior
 * `WatchlistMover` shape with cross-service enrichment columns. */
export interface WatchlistMoverEnriched {
  instrument_id: string;
  /** KG entity_id when known — null for unresolved members. */
  entity_id: string | null;
  ticker: string;
  name: string;
  /** GICS sector (Information Technology, Health Care, …) — null when the
   *  per-member overview lookup did not return a sector. */
  sector: string | null;
  /** Latest price; null while loading or when the quote endpoint failed. */
  price: number | null;
  /** Change_pct in percent units (e.g. 1.5 means +1.50%). */
  change_pct: number | null;
  /** Articles in the last 24h whose entity_ids include this member. */
  news_count_24h: number;
  /** True when there is at least one pending alert for this member's entity. */
  has_active_alert: boolean;
  /** Top-impact 24h article title for this member (for the per-row badge). */
  top_news_title: string | null;
  /** External URL for the top-news article (opens in new tab). */
  top_news_url: string | null;
}

/** GICS sector breakdown row — for the stacked horizontal mini-bar. */
export interface WatchlistSectorBucket {
  sector: string;
  count: number;
  /** count / members_count — pre-computed so the widget renders without math. */
  weight: number;
}

/** Single-biggest-news callout row above the gainers/losers split. */
export interface WatchlistBiggestNews {
  article_id: string | null;
  title: string | null;
  url: string | null;
  published_at: string | null;
  ticker: string | null;
  /** market_impact_score in [0..1]; null when the article had no impact score. */
  impact_score: number | null;
}

export interface WatchlistInsights {
  watchlist_id: string;
  members_count: number;
  movers: WatchlistMoverEnriched[];
  /** Equal-weighted average change_pct across members with a live quote.
   *  Null when no member has a quote yet (loading) or the watchlist is empty. */
  weighted_return_1d: number | null;
  sectors: WatchlistSectorBucket[];
  biggest_news: WatchlistBiggestNews | null;
  /** Total pending alerts that match any member's entity_id. */
  alerts_count: number;
}

// ── Alerts ─────────────────────────────────────────────────────────────────

export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Alert {
  alert_id: string;
  entity_id: string;
  ticker: string | null;
  alert_type: string;
  severity: AlertSeverity;
  // WHY title is `string | null` (not `string`):
  // PLAN-0049 added a backend-composed `title` column to the alerts table; old
  // alerts persisted before the migration are NULL. Frontend uses a fallback
  // ladder (title → signal_label → humanised alert_type) — making title
  // non-nullable here would require populating it for legacy rows, which
  // PLAN-0049 explicitly chose not to do (fallback chain handles it).
  title: string | null;
  body: string;
  // PLAN-0049 T-A-1-02 enrichment fields. All optional / nullable:
  // - Old alerts persisted before migration 0006 will have these as NULL.
  // - Forward-compat (additive) so older clients ignoring them keep working.
  entity_name?: string | null;
  signal_label?: string | null;
  // WHY payload: S10 PendingAlertResponse returns payload (dict) as the structured data.
  // body/title/ticker are legacy fields that may not be populated by the current API.
  payload?: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  acknowledged_at: string | null;
}

export interface AlertsResponse {
  alerts: Alert[];
  total: number;
  offset: number;
  limit: number;
}

// ── Chat ───────────────────────────────────────────────────────────────────

export interface Message {
  message_id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
}

export interface Citation {
  article_id: string;
  title: string;
  url: string;
  source: string;
  relevance_score: number;
}

export interface Thread {
  thread_id: string;
  title: string | null;
  owner_id: string;
  messages: Message[];
  created_at: string;
  updated_at: string;
}

export interface ChatStreamRequest {
  question: string;
  thread_id: string;
}

// ── Prediction Markets ────────────────────────────────────────────────────

export interface PredictionMarket {
  market_id: string;
  title: string;
  description: string;
  yes_probability: number; // 0.0–1.0
  no_probability: number;
  volume_usd: number;
  status: "open" | "closed" | "resolved";
  resolution_date: string | null;
  entity_ids: string[];
  tickers: string[];
  source: "polymarket" | "kalshi";
  url: string;
  // WHY market_slug: PLAN-0043 B-2 added market_slug to S3 DB + S9 response.
  // Enables constructing canonical Polymarket URLs (polymarket.com/event/{slug})
  // instead of a title-search fallback. Nullable because older rows lack the slug.
  market_slug: string | null;
  // PLAN-0049 T-C-3-03: server-side category filter (?category=politics).
  // Optional — adapter populates it from Polymarket Gamma `tags` on a future
  // wave; existing rows surface as null until backfilled.
  category?: string | null;
  updated_at: string;
}

export interface PredictionMarketsResponse {
  markets: PredictionMarket[];
  total: number;
}

// ── Economic Calendar ─────────────────────────────────────────────────────

export type EconomicImpact = "HIGH" | "MEDIUM" | "LOW";

export interface EconomicEvent {
  event_id: string;
  title: string;
  country: string;
  currency: string | null;
  event_date: string; // ISO 8601 UTC
  forecast: number | null;
  previous: number | null;
  actual: number | null;
  impact: EconomicImpact;
  unit: string | null;
}

export interface EconomicCalendarResponse {
  events: EconomicEvent[];
}

// ── Briefings ─────────────────────────────────────────────────────────────

/** Entity reference extracted from briefing context (portfolio, news, alerts) */
export interface BriefingEntityMention {
  entity_id: string;
  name: string;
  ticker: string | null;
}

/** Source that informed the briefing — deterministic, from gathered context (not LLM output) */
export interface BriefingCitation {
  source_type: "article" | "event" | "alert";
  source_id: string;
  title: string;
  url: string | null;
}

/** Response from GET /api/v1/briefings/* — matches S8 PublicBriefingResponse */
export interface BriefingResponse {
  // WHY narrative (not content): S8's PublicBriefingResponse schema uses the field
  // name "narrative" — the internal BriefingResponse model uses "narrative" as well.
  // The route handler maps execute_public_morning()'s "content" key → "narrative"
  // before serialising. See: services/rag-chat/src/rag_chat/api/schemas.py line 117.
  narrative: string;
  // WHY summary is optional + nullable (PLAN-0048 Wave A):
  // The v2.2 MORNING_BRIEFING prompt splits its output into a ``## SUMMARY``
  // block (1-2 sentences) and a ``## DETAILS`` block. The S8 use case parses
  // them apart and ships the summary half here. Older cached briefings
  // generated before the v2.2 rollout will lack this field entirely (hence
  // optional `?`), and instrument briefs always pass null (hence `| null`).
  // The MorningBriefCard falls back to clamp-3 of the narrative when null —
  // never break rendering when summary is missing.
  summary?: string | null;
  risk_summary: {
    concentration_score: number;
    top_risk_signals: Array<{ signal_id: string; description: string }>;
    sector_breakdown: Record<string, number>;
  } | null;
  entity_mentions: BriefingEntityMention[];
  citations: BriefingCitation[];
  generated_at: string;
  cached: boolean;
  entity_id: string | null;
  // PLAN-0049 T-A-1-04 — structured render fields. ``sections`` is populated
  // when the backend's _parse_sections_from_markdown() succeeded; ``[]`` when
  // it couldn't parse, in which case the frontend falls back to MarkdownContent
  // over ``narrative``. ``headline`` mirrors ``summary`` for the top-of-card line.
  headline?: string | null;
  sections?: BriefSection[];
}

/** A structured section of a brief — populated when the backend parser succeeds. */
export interface BriefSection {
  title: string;
  bullets: string[];
}

// ── Market Heatmap ────────────────────────────────────────────────────────

export interface HeatmapSector {
  name: string;
  change_pct: number | null;
  instrument_count: number;
}

export interface MarketHeatmapResponse {
  sectors: HeatmapSector[];
}

// ── Top Movers ────────────────────────────────────────────────────────────

export interface Mover {
  instrument_id: string;
  // WHY optional entity_id: The top-movers endpoint is backed by S3's screener which does
  // not always return entity_id (S3 uses instrument_id as its primary key). When S9 surfaces
  // entity_id in the top-movers response, it is populated here. Until then it remains
  // undefined and navigation falls back to using instrument_id, which the instrument detail
  // page's S9 overview endpoint accepts via either identifier (ADR-F-12 note in [entityId]/page.tsx).
  entity_id?: string | null;
  ticker: string;
  name: string;
  price: number;
  change_pct: number;
  volume: number | null;
}

export interface TopMoversResponse {
  movers: Mover[];
  type: "gainers" | "losers";
}

// ── Search ────────────────────────────────────────────────────────────────

export interface SearchResult {
  instrument_id: string;
  entity_id: string;
  ticker: string;
  name: string;
  exchange: string;
  type: string; // "equity", "etf", "crypto", "index"
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
}

// ── AI Signals ────────────────────────────────────────────────────────────

export interface AiSignal {
  signal_id: string;
  entity_id: string;
  ticker: string | null;
  label: "POSITIVE" | "NEGATIVE" | "NEUTRAL";
  score: number; // 0.0–1.0
  article_title: string | null;
  created_at: string;
}

export interface AiSignalsResponse {
  signals: AiSignal[];
}

// ── Brokerage ──────────────────────────────────────────────────────────────

/**
 * BrokerageConnection — a SnapTrade brokerage link for a portfolio.
 *
 * WHY status enum: status drives all UI decisions — which buttons to show,
 * which badge color to use, whether sync is possible. Keeping it typed
 * prevents string typos from reaching the UI.
 *
 * DATA SOURCE: S9 GET /api/v1/brokerage-connections
 * DESIGN REFERENCE: PRD-0022 §6.6
 */
export interface BrokerageConnection {
  connection_id: string;      // UUIDv7 — stable identifier across retries
  portfolio_id: string;
  brokerage_name: string | null; // null when SnapTrade hasn't confirmed broker yet
  status: "pending" | "active" | "error" | "disconnected";
  last_synced_at: string | null; // ISO UTC — null if never synced successfully
  created_at: string;
}

export interface BrokerageConnectionsResponse {
  items: BrokerageConnection[];
}

export interface InitiateBrokerageConnectionResponse {
  connection_id: string;  // pre-created so we can embed it in the redirect URI
  redirect_uri: string;   // SnapTrade portal URL — frontend immediately redirects here
}

/**
 * SyncError — a transaction-level error recorded during a SnapTrade sync.
 *
 * WHY non-blocking: these are transaction-level errors (e.g., unknown instrument),
 * not connection-level failures. The connection stays active and continues syncing
 * other transactions. The UI shows them as warnings, not errors.
 *
 * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/sync-errors
 * DESIGN REFERENCE: PRD-0022 §6.6
 */
export interface SyncError {
  id: string;
  connection_id: string;
  snaptrade_transaction_id: string;
  error_type: "unknown_instrument" | "unsupported_type" | "api_error" | "validation_error";
  error_detail: string | null;
  created_at: string;
}

export interface SyncErrorsResponse {
  items: SyncError[];
}

// ── Pagination helper ─────────────────────────────────────────────────────

export interface PaginationParams {
  limit?: number;
  offset?: number;
}
