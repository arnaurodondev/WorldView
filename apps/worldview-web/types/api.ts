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
  entity_id: string; // WHY separate: entity_id ≠ instrument_id (ADR-F-12)
  ticker: string;    // e.g., "AAPL"
  name: string;      // e.g., "Apple Inc."
  exchange: string;  // e.g., "NASDAQ"
  currency: string;  // e.g., "USD"
  gics_sector: string | null;
  gics_industry: string | null;
  isin: string | null;
  country: string | null;
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
}

export interface NewsResponse {
  articles: Article[];
  total: number;
  offset: number;
  limit: number;
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
  // Key metrics for screener table — all may be null if data not available
  market_cap: number | null;
  pe_ratio: number | null;
  daily_return: number | null;
  market_impact_score: number | null; // PRD-0020 signal score
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
  type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fee: number;
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

// ── Watchlist ──────────────────────────────────────────────────────────────

export interface WatchlistMember {
  entity_id: string;
  instrument_id: string | null;
  ticker: string | null;
  name: string;
  added_at: string;
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

export interface MorningBrief {
  brief_id: string;
  content: string;    // markdown
  generated_at: string;
  entity_mentions: Array<{ entity_id: string; name: string; ticker: string | null }>;
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

// ── Pagination helper ─────────────────────────────────────────────────────

export interface PaginationParams {
  limit?: number;
  offset?: number;
}
