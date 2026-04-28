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
}

export interface ValueHistoryResponse {
  points: ValueHistoryPoint[];
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
    status: "ok" | "insufficient_data" | "benchmark_unavailable";
    n_returns: number;
    lookback_days: number;
  };
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

// ── Alerts ─────────────────────────────────────────────────────────────────

export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Alert {
  alert_id: string;
  entity_id: string;
  ticker: string | null;
  alert_type: string;
  severity: AlertSeverity;
  title: string;
  body: string;
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
