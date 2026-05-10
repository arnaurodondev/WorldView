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
 *
 * CODEGEN STATUS (PLAN-0070-B-3 — 2026-05-03):
 *   Generated path types live in types/generated/api.ts (run npx openapi-typescript
 *   infra/contracts/s9-openapi.json -o apps/worldview-web/types/generated/api.ts
 *   to refresh from infra/contracts/s9-openapi.json).
 *
 *   As of PLAN-0070 Waves B-1 + B-2, S9 now has 26 named component schemas
 *   (Tier-1 + Tier-2 response_model annotations). The generated spec has correct
 *   OpenAPI shapes for QuoteResponse, NewsTopResponse, PortfolioResponse, etc.
 *
 *   WHY hand-written types STILL remain (PLAN-0070-B-3 finding):
 *   The generated Pydantic schemas use `extra="allow"`, which openapi-typescript
 *   translates to `& { [key: string]: unknown }`. This covers additional backend
 *   fields at runtime but REMOVES TypeScript's named type safety for optional
 *   fields added post-schema (e.g. Quote.freshness_status, Quote.data_as_of,
 *   Quote.stale_reason). Components that index into Quote["freshness_status"]
 *   (StaleBadge.tsx, LiveQuoteBadge.tsx) would break if Quote were replaced with
 *   the generated alias — TypeScript would no longer know the field exists.
 *
 *   Full migration requires the Pydantic schemas to declare every optional field
 *   explicitly (not relying on extra="allow"). Once that backend work is done,
 *   replace each hand-written type with the path-keyed alias pattern:
 *     export type Quote = S9Paths["/v1/quotes/{instrument_id}"]["get"]["responses"]["200"]["content"]["application/json"]
 *
 *   Until then, the hand-written types below ARE the authoritative source of truth.
 *   The S9Gen aliases below provide access to the generated shapes for callers that
 *   want to work with the spec-level types directly (e.g. contract tests).
 */

// ── Generated path surface (PLAN-0059-C1) ─────────────────────────────────
// WHY re-export: makes the generated path/operation/component types available to
// any consumer that needs to type-check against the raw spec surface (e.g. the
// drift-gate test, typed fetch helpers). The aliases below expose the useful
// generated sub-types under stable names.
export type { paths as S9Paths, components as S9Components, operations as S9Operations } from "./generated/api";

// ── Named aliases for generated component schemas (PLAN-0070-B-3) ─────────
// WHY import type (not value): openapi-typescript generates pure type definitions.
// WHY separate from hand-written types: these aliases provide access to the exact
// schema shapes that S9's Pydantic models define — useful for contract tests and
// type-narrowing helpers that need to work at the spec level. Hand-written types
// (Quote, Portfolio, etc.) remain the authoritative types for UI components because
// they declare all optional fields by name (see CODEGEN STATUS comment above).
import type { components as S9Gen } from "./generated/api";
/** Pydantic ValidationError shape returned on 422 responses. */
export type S9ValidationError = S9Gen["schemas"]["HTTPValidationError"];
/** Admin LLM cost breakdown response (GET /v1/admin/llm/costs). */
export type S9AdminLlmCostsResponse = S9Gen["schemas"]["AdminLlmCostsResponse"];
/** POST /v1/ohlcv/batch request body. */
export type S9BatchOHLCVRequest = S9Gen["schemas"]["_BatchOHLCVRequest"];
// Tier-1 response schemas (added in PLAN-0070 Wave B-1)
/** Generated shape of GET /v1/quotes/{instrument_id} 200 response. */
export type S9QuoteResponse = S9Gen["schemas"]["QuoteResponse"];
/** Generated shape of GET /v1/news/top 200 response (articles array container). */
export type S9NewsTopResponse = S9Gen["schemas"]["NewsTopResponse"];
/** Generated shape of a single news article from GET /v1/news/top. */
export type S9NewsArticle = S9Gen["schemas"]["NewsArticle"];
/** Generated shape of a single portfolio from GET /v1/portfolios. */
export type S9PortfolioResponse = S9Gen["schemas"]["PortfolioResponse"];
/** Generated shape of GET /v1/ohlcv/{instrument_id} 200 response. */
export type S9OHLCVResponse = S9Gen["schemas"]["OHLCVResponse"];
/** Generated shape of a single OHLCV bar. */
export type S9OHLCVBar = S9Gen["schemas"]["OHLCVBar"];
/** Generated shape of a single pending alert from GET /v1/alerts/pending. */
export type S9AlertResponse = S9Gen["schemas"]["AlertResponse"];
/** Generated shape of a single watchlist from GET /v1/watchlists. */
export type S9WatchlistResponse = S9Gen["schemas"]["WatchlistResponse"];
/** Generated shape of a single instrument search result from GET /v1/search/instruments. */
export type S9InstrumentSearchResult = S9Gen["schemas"]["InstrumentSearchResult"];
// Tier-2 response schemas (added in PLAN-0070 Wave B-2)
/** Generated shape of POST /v1/fundamentals/screen response. */
export type S9ScreenerResponse = S9Gen["schemas"]["ScreenerResponse"];
/** Generated shape of a single screener result row. */
export type S9ScreenerResultItem = S9Gen["schemas"]["ScreenerResultItem"];
/** Generated shape of GET /v1/signals/prediction-markets response. */
export type S9PredictionMarketsListResponse = S9Gen["schemas"]["PredictionMarketsListResponse"];
/** Generated shape of a single prediction market. */
export type S9PredictionMarket = S9Gen["schemas"]["PredictionMarket"];
/** Generated shape of GET /v1/fundamentals/earnings-calendar response. */
export type S9EarningsCalendarResponse = S9Gen["schemas"]["EarningsCalendarResponse"];
/** Generated shape of a single earnings calendar event. */
export type S9EarningsEvent = S9Gen["schemas"]["EarningsEvent"];
/** Generated shape of GET /v1/fundamentals/{id} response. */
export type S9FundamentalsResponse = S9Gen["schemas"]["FundamentalsResponse"];
/** Generated shape of a single fundamentals section record. */
export type S9FundamentalsRecord = S9Gen["schemas"]["FundamentalsRecord"];

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
  // Analyst consensus — assembled from EODHD analyst_consensus section
  // (audit 2026-05-09: data was always present in /v1/fundamentals/{id} but
  // the AnalystConsensusStrip component ignored it and rendered a placeholder).
  // All counts are absolute analyst counts (not percentages).
  analyst_strong_buy_count: number | null;
  analyst_buy_count: number | null;
  analyst_hold_count: number | null;
  analyst_sell_count: number | null;
  analyst_strong_sell_count: number | null;
  // EODHD's combined recommendation rating: 1.0 (Strong Sell) — 5.0 (Strong Buy)
  analyst_rating: number | null;
  // Wall Street consensus 12-month price target (USD)
  analyst_target_price: number | null;
  updated_at: string | null; // ISO 8601 UTC; null if no fundamentals backfill has run yet
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

/**
 * InstrumentPageBundle — PLAN-0059 I-5 single-round-trip composite for
 * /instruments/[id] initial page load.
 *
 * Returned by GET /v1/instruments/{id}/page-bundle. The S9 endpoint composes
 * 5 downstream calls via asyncio.gather; per-call failures degrade
 * gracefully (the failed sub-resource is null in the response). Existing
 * dedicated endpoints remain available — components may still hit
 * /v1/companies/{id}/overview, /v1/fundamentals/{id}, etc. if they need
 * fresher data than the bundle's cached snapshot.
 *
 * Sub-resource shapes match the dedicated endpoints' responses verbatim so
 * the FE can prime its TanStack Query caches with bundle.* values.
 */
export interface InstrumentPageBundle {
  instrument_id: string;
  /** KG entity_id resolved by the gateway via ticker → KG lookup. Falls back to instrument_id. */
  entity_id: string;
  /** CompanyOverview composite (instrument + quote + fundamentals header + 90d ohlcv). */
  overview: CompanyOverview | null;
  /** Full all-sections fundamentals (mirrors /v1/fundamentals/{id}). */
  fundamentals: FundamentalsSectionResponse | null;
  /** Technicals snapshot (52-week range etc.). */
  technicals: FundamentalsSectionResponse | null;
  /** Insider transactions records. */
  insider: FundamentalsSectionResponse | null;
  /** Top-N entity-scoped news (limit=5). */
  top_news: RankedNewsResponse | null;
}

// ── Knowledge Graph ────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;         // entity_id
  label: string;      // entity name
  type: string;       // "company", "person", "event", "topic"
  size?: number;      // relative importance score for sigma.js node sizing
  x?: number;         // layout position (set by sigma.js)
  y?: number;
  /** Ticker symbol — included by S9 proxy for financial_instrument nodes so
   *  components can resolve entity_id → S3 instrument without a second lookup.
   *  Empty string for non-instrument entities (sectors, people, events).
   *  WHY needed: KG entity_id ≠ S3 instrument_id; ticker is the stable bridge. */
  ticker?: string;
}

export interface GraphEdge {
  id: string;
  source: string;     // entity_id
  target: string;     // entity_id
  /** Relationship type — always lowercase (S9 normalises DB mixed-case).
   *  Examples: "competes_with", "has_executive", "listed_on" */
  label: string;
  weight: number;     // confidence / strength [0, 1]
  /** One-line LLM summary from relation_summaries (Worker 13C). Null when
   *  no summary has been generated yet (table empty pre-SummaryWorker run). */
  relation_summary?: string | null;
  /** Top evidence text snippets (max 3, from relation_evidence_raw). */
  evidence_snippets?: string[];
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

// ── Entity enrichment (PRD-0073 Worker 13J) ───────────────────────────────

/** Structured enrichment metadata fields sourced from S3/EODHD or LLM.
 *
 * F-A14 / F-P2-04: keep this in sync with the backend Pydantic model
 * `EntityMetadata` in services/knowledge-graph/.../api/schemas.py — the 5
 * non-financial fields below are needed for `person`, `concept`, `location`,
 * and `event` entity types whose data_completeness formula references them.
 */
export interface EntityMetadata {
  // Financial-instrument / company fields
  sector?: string | null;
  industry?: string | null;
  country?: string | null;
  exchange?: string | null;
  isin?: string | null;
  ticker?: string | null;
  currency_code?: string | null;
  employee_count?: number | null;
  founded_year?: number | null;
  headquarters_city?: string | null;
  headquarters_country?: string | null;
  // Person fields
  role?: string | null;
  organization?: string | null;
  nationality?: string | null;
  // Concept / location fields
  category?: string | null;
  // Macro indicator entity fields
  macro_indicators?: Record<string, unknown> | null;
}

/**
 * EntityPublic — response shape for GET /api/v1/entities/{entity_id}.
 * Populated by Worker 13J (StructuredEnrichmentWorker).
 */
export interface EntityPublic {
  entity_id: string;
  canonical_name: string;
  entity_type: string;
  ticker?: string | null;
  isin?: string | null;
  exchange?: string | null;
  description?: string | null;
  data_completeness?: number | null;
  enriched_at?: string | null;
  metadata: EntityMetadata;
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
  // SA-4: near-duplicate cluster size enriched by S9 gateway from content-store.
  // cluster_size=1 → no near-duplicates; cluster_size=N → N-1 sibling articles.
  // null when enrichment was skipped (e.g. content-store outage).
  cluster_size: number | null;
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

/**
 * ScreenerFilter — a single filter clause sent to POST /v1/fundamentals/screen.
 *
 * WHY both shapes are accepted (PLAN-0051):
 *   - Legacy `{field, operator, value}` form (used by older call sites).
 *   - PLAN-0051 Wave B `{metric, min_value, max_value, sector}` form (range
 *     filters with optional sector restriction). The backend's actual schema
 *     is the metric/min/max form; the legacy form is being phased out.
 *
 * All keys are optional so a single TS interface covers both shapes; runtime
 * code is responsible for sending one or the other coherently.
 */
export interface ScreenerFilter {
  // Legacy form
  field?: string;
  operator?: string;
  value?: number | string | string[];
  // Range form (PLAN-0051 Wave B)
  metric?: string;
  min_value?: number;
  max_value?: number;
  sector?: string;
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
  /**
   * PLAN-0053 T-D-4-02: instrument asset class — surfaced from
   * ``instruments.asset_class`` via the ListTransactionsUseCase JOIN.
   * One of ``equity | etf | option | future | bond | crypto | unknown``
   * (the API does not enforce a closed enum so adapters can introduce new
   * values without a breaking schema change). Nullable when the instrument
   * row hasn't synced yet — the table renders a muted "—" badge in that
   * case rather than a misleading default.
   */
  asset_class: string | null;
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

// ── Portfolio Bundle (PLAN-0070 C-1) ─────────────────────────────────────────

/**
 * GET /v1/portfolio/{portfolio_id}/bundle response.
 *
 * Collapses 4 portfolio page requests into one round-trip (PLAN-0070 C-1).
 * Each leg is independently nullable — bundle_meta.partial=true when any
 * downstream call failed. Components must handle null gracefully by rendering
 * "—" or a skeleton state for the missing section.
 *
 * WHY value_history not equity_curve: the S1 endpoint is /value-history and
 * the type name mirrors the existing ValueHistoryResponse convention.
 *
 * WHY _meta uses a leading underscore: the Python backend returns "_meta" as
 * a dict key (not a typed field); Pydantic extra="allow" passes it through.
 * TypeScript types the key name verbatim here to match the wire shape.
 */
export interface PortfolioBundleResponse {
  portfolio_id: string;
  /** Raw S1 PortfolioResponse shape. null when portfolio fetch failed. */
  portfolio: Portfolio | null;
  /**
   * Raw S1 holdings envelope. null when holdings fetch failed.
   * WHY raw dict (not HoldingsResponse): the bundle leg returns the S1 native
   * shape (PaginatedResponse[HoldingResponse] = {items, total, limit, offset}).
   * The dedicated getHoldings() transform is not run on bundle-fetched data.
   * Consumers of this field should use getHoldings() for full transformation.
   */
  holdings: Record<string, unknown> | null;
  /**
   * Raw S1 transactions envelope. null when transactions fetch failed.
   * Capped at 30 items. Use getTransactions() for full paginated access.
   */
  transactions: Record<string, unknown> | null;
  /**
   * Raw S1 value-history response. null when value-history fetch failed.
   * WHY period=1Y: bundle always fetches 1Y for the equity curve chart.
   */
  value_history: Record<string, unknown> | null;
  // WHY _meta key (not bundle_meta): the wire protocol uses "_meta" as a
  // top-level JSON key. TypeScript can index arbitrary string keys via
  // Record<> but typing it as optional here makes the partial check explicit.
  _meta?: { partial: boolean; legs_failed: number; timed_out?: boolean };
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
  // PLAN-0051 Wave D additions — backend may set these via PATCH /acknowledge
  // and /snooze. All optional so legacy responses (pre-migration) still parse.
  // ISO-8601 UTC datetime when the alert is muted. `null` once the snooze
  // expires or has never been set.
  snooze_until?: string | null;
  // Optional analyst note attached at ACK time; never displayed on the
  // sidebar/list — surfaced only inside the AlertDetailSheet.
  ack_note?: string | null;
  // _localOnly is a CLIENT-SIDE marker injected when the backend endpoint
  // returns 404 — we still ACK/snooze in localStorage and tag the row so the
  // UI can render a "(local only)" badge until the backend ships.
  _localOnly?: boolean;
}

export interface AlertsResponse {
  alerts: Alert[];
  /**
   * Total universe count matching the filters (NOT the page-row count).
   * Pinned by S10's `AlertHistoryResponse.total` after QA-iter1 C-3 fix.
   * Frontends use `rows.length < total` (or `has_more`) to render "Load more".
   */
  total: number;
  offset: number;
  limit: number;
  /**
   * Optional server-computed convenience flag — true iff `offset + alerts.length
   * < total`. The History tab prefers `has_more` when present and falls back
   * to deriving from total. Marked optional because PendingAlertsResponse
   * (which shares this shape) does not yet emit it.
   */
  has_more?: boolean;
}

/**
 * AlertHistoryParams — filters for the /v1/alerts/history endpoint.
 *
 * WHY all optional: an empty object means "everything, paginated 50 at a
 * time" which is the History tab default state. Each filter narrows the
 * server-side query.
 */
export interface AlertHistoryParams {
  status?: "active" | "acknowledged" | "snoozed" | "all";
  severity?: AlertSeverity;
  /** ISO-8601 UTC datetime — lower bound on `created_at`. */
  from?: string;
  /** ISO-8601 UTC datetime — upper bound on `created_at`. */
  to?: string;
  entity_id?: string;
  limit?: number;
  offset?: number;
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
  /** PLAN-0071 P2A-1: entity-page context injected by AskAiPanel/AnalystRail.
   *  When present, S8 uses this as a system-level prefix so the model is
   *  context-aware without the user having to re-state the instrument. */
  system_context?: string;
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

// ── Earnings Calendar ──────────────────────────────────────────────────────

/**
 * EarningsEvent — one company earnings report from S9 /v1/fundamentals/earnings-calendar.
 *
 * WHY region = ticker: The earnings-calendar consumer (13D-9) stores the
 * company ticker symbol in `region` because temporal_events.region is a
 * free-text label (not a country code) for company-scoped events.
 *
 * WHY confidence: Finnhub sourced events with a confirmed report date get
 * confidence=1.0; tentative-date events (epsEstimate=null) are skipped by
 * the consumer so this field is always 1.0 in practice.
 *
 * DATA SOURCE: S9 GET /v1/fundamentals/earnings-calendar → S7 temporal-events
 * (event_type=corporate). PLAN-0068 Wave A-1 / A-2.
 */
export interface EarningsEvent {
  event_id: string;
  title: string;        // e.g. "AAPL Q3 2026 Earnings"
  description: string;  // e.g. "EPS est. $1.45 (BMO)"
  active_from: string;  // ISO 8601 UTC — report datetime
  active_until: string; // ISO 8601 UTC — residual end (+7 days)
  region: string;       // ticker symbol, e.g. "AAPL"
  confidence: number;   // always 1.0 for confirmed earnings dates
}

export interface EarningsCalendarResponse {
  events: EarningsEvent[];
  total: number;
}

// ── Briefings ─────────────────────────────────────────────────────────────

/** Entity reference extracted from briefing context (portfolio, news, alerts) */
export interface BriefingEntityMention {
  entity_id: string;
  name: string;
  ticker: string | null;
}

/**
 * BriefCitation — a structured source document attached to a brief bullet.
 *
 * WHY document_id (not source_id): PLAN-0062-W4 migrated the backend Pydantic
 * model to `document_id` to align with the KG document vocabulary. We keep
 * `source_id` as an optional back-compat alias so pre-W4 cached responses
 * (which emit `source_id`) still parse correctly.
 *
 * WHY `source_type` Literal: discriminates news articles, economic events, and
 * alerts so the renderer can apply per-type UI treatment (e.g. an anchor tag
 * for articles, an event chip for economic events).
 *
 * DATA SOURCE: S8 BriefCitation Pydantic model (PLAN-0062-W4 T-W4-A-01)
 */
export interface BriefCitation {
  // Primary identifier — populated by W4+ API responses.
  document_id: string;
  // Legacy back-compat alias — populated by pre-W4 cached responses.
  // WHY optional: not present in W4+ responses; optional avoids forced migration.
  source_id?: string;
  // Human-readable title (article headline, event name, alert description).
  title: string;
  // Direct URL to the source; null for events/alerts that have no external URL.
  url: string | null;
  // Discriminator — drives per-type UI treatment in StructuredBrief.
  source_type: "article" | "event" | "alert";
  // Short excerpt (≤ 400 chars) from the source document used as a tooltip.
  // WHY optional: pre-W4 cached responses lack this field.
  snippet?: string | null;
}

/**
 * BriefingCitation — legacy shape emitted by pre-W4 API responses.
 *
 * WHY keep this: The morning brief card and instrument brief panel both
 * read `brief.citations` to build the Top Stories chip strip. Pre-W4 cached
 * responses emit `BriefingCitation` objects (with `source_id`); W4+ responses
 * emit `BriefCitation` objects (with `document_id`). Both shapes must parse.
 *
 * DEPRECATION NOTE: Use `BriefCitation` for all new code. This alias is kept
 * only for backward compatibility during the cache warm-up window after W4
 * deploy. Remove after cache TTL (24h) expires.
 *
 * DATA SOURCE: S8 BriefingCitation (pre-W4 schema, PLAN-0049)
 */
export interface BriefingCitation {
  source_type: "article" | "event" | "alert";
  source_id: string;
  title: string;
  url: string | null;
}

/**
 * BriefBullet — a single bullet point with mandatory citations (PLAN-0062-W4).
 *
 * WHY citations are required (not optional): the 100% citation gate is the
 * core contract of PLAN-0062-W4. Every bullet MUST reference ≥ 1 source
 * document. The `_backfill_uncited_bullets` function on the backend drops
 * any bullet that couldn't resolve a citation, so the frontend can safely
 * assume this invariant holds for W4+ responses.
 *
 * WHY optional `citations`: pre-W4 cached responses have `bullets: string[]`.
 * The `BriefSection.bullets` type is `BriefBullet[]`, so string bullets from
 * pre-W4 caches will fail Pydantic validation — the route serves a cache miss
 * instead (see the v2 cache key bump in PLAN-0062-W4 T-W4-C-01). We mark
 * `citations` optional here ONLY so TypeScript doesn't force callers to supply
 * citations when adapting legacy string bullets in tests.
 *
 * DATA SOURCE: S8 BriefBullet Pydantic model (PLAN-0062-W4 T-W4-A-01)
 */
export interface BriefBullet {
  // The bullet text (≤ 400 chars, ≥ 1 char).
  text: string;
  // Resolved source citations for this bullet — guaranteed non-empty by the
  // backend's citation gate for W4+ responses.
  // WHY optional: allows test adapters to construct BriefBullet from legacy
  // string bullets without supplying citations (see morning-brief-card.test.tsx).
  citations?: BriefCitation[];
}

/** Response from GET /api/v1/briefings/* — matches S8 PublicBriefingResponse */
export interface BriefingResponse {
  // PLAN-0066 Wave F: the DB id of the persisted brief (UUID string).
  // Optional because older cached responses and non-archived briefs won't have it.
  // Used by BulletFeedback, BriefRating, and BriefEntityPill to POST with brief_id.
  id?: string | null;
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
  // WHY entity_mentions optional: PLAN-0062-W4 removes entity_mentions from the
  // critical path — the backend no longer guarantees they are populated. The
  // frontend defensively falls back to `brief.entity_mentions ?? []` everywhere.
  entity_mentions?: BriefingEntityMention[];
  // WHY union type: W4+ responses emit `BriefCitation[]` (with `document_id`);
  // pre-W4 cached responses emit `BriefingCitation[]` (with `source_id`).
  // Both shapes share `source_type`, `title`, and `url` — the URL is all the
  // frontend needs to render the Top Stories chip strip.
  citations: (BriefCitation | BriefingCitation)[];
  generated_at: string;
  cached: boolean;
  entity_id: string | null;
  // Structured sections — populated when the backend parsed the ## DETAILS
  // block; ``[]`` on legacy/parse-failure paths (frontend falls back to
  // MarkdownContent over ``narrative``).
  sections?: BriefSection[];
  // PLAN-0062-W4 T-W4-D-01 — confidence + lead fields.
  // ``confidence`` is a [0.0, 1.0] score reflecting citation density and breadth.
  // ``lead`` is the 1-3 sentence executive summary from the ## LEAD block of the
  // v3.0 prompt output, with inline [cN] citation markers.
  // WHY optional: pre-W4 cached responses lack these fields. The frontend renders
  // the confidence badge only when present, and falls back to ``summary`` when
  // ``lead`` is absent.
  confidence?: number;
  lead?: string | null;
}

/**
 * BriefSection — a structured section of a brief with W4+ citation bullets.
 *
 * WHY bullets is `BriefBullet[]` (not `string[]`): PLAN-0062-W4 changed the
 * backend Pydantic model from `list[str]` to `list[BriefBullet]`. Any attempt
 * to construct a BriefSection with string bullets from a v2 cache key will
 * fail Pydantic validation, causing a cache miss and fresh generation.
 *
 * WHY back-compat via test adapter: existing tests that build BriefingResponse
 * fixtures with `bullets: string[]` must adapt using `_toBriefBullet()` helpers
 * in the test file — R19 forbids deleting/weakening existing tests.
 *
 * DATA SOURCE: S8 BriefSection Pydantic model (PLAN-0062-W4 T-W4-A-01)
 */
export interface BriefSection {
  title: string;
  // W4+ responses: array of BriefBullet objects (each with ≥1 citation).
  // Pre-W4 cached responses: NOT served (v2 cache key forces regeneration).
  bullets: BriefBullet[];
}

// ── Brief History + Diff (PLAN-0066 Wave F) ───────────────────────────────

/**
 * BriefHistoryItem — a lightweight summary of one past morning brief.
 * Returned by GET /api/v1/briefings/morning/history.
 *
 * WHY no sections/bullets: history list shows headline + lead only.
 * Full structured content is fetched per-brief when the user requests it.
 */
export interface BriefHistoryItem {
  id: string;
  generated_at: string;
  headline: string;
  lead: string | null;
  confidence: number;
}

/**
 * BriefDiffBullet — one bullet that appeared or disappeared between briefs.
 * citations is `unknown[]` because the backend's DiffBullet dataclass uses
 * a raw `list[dict]` — the frontend only needs the `text` field for display.
 */
export interface BriefDiffBullet {
  section_title: string;
  text: string;
  citations: unknown[];
}

/**
 * BriefDiffResponse — result of GET /api/v1/briefings/morning/diff.
 *
 * status:
 *   "diff_available"    — two briefs found; new_bullets/removed_bullets populated
 *   "no_diff_available" — fewer than 2 briefs; nothing to compare
 *
 * WHY delta_summary as human-readable string: the backend already formats it
 * (e.g. "3 new bullets, 1 removed since 2026-05-07") — the frontend just renders it.
 */
export interface BriefDiffResponse {
  status: "diff_available" | "no_diff_available";
  today_generated_at: string | null;
  yesterday_generated_at: string | null;
  new_bullets: BriefDiffBullet[];
  removed_bullets: BriefDiffBullet[];
  changed_sections: string[];
  delta_summary: string;
}

/**
 * BriefAlertPrefillResponse — result of POST /api/v1/briefings/{id}/create-alert.
 * Contains pre-filled fields for opening the alert creation drawer from a brief bullet.
 */
export interface BriefAlertPrefillResponse {
  entity_id: string | null;
  entity_name: string | null;
  suggested_alert_type: string;
  context_snippet: string;
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

// ── Dashboard Snapshot Bundle (PLAN-0070 C-2) ─────────────────────────────

/**
 * DashboardSnapshotResponse — all dashboard initial data in one request.
 *
 * WHY: replaces 6+ individual useQuery hooks on the dashboard page with a
 * single bundle call to GET /v1/dashboard/snapshot. S9 fans out to 6 upstream
 * services concurrently and returns them in one response.
 *
 * Per-leg null means that upstream call failed — the frontend renders "—" or
 * a skeleton for null legs. _meta.partial=true when any leg is null.
 *
 * NOT included in the snapshot (require per-instrument lookups or lazy-load):
 *   - top movers  : N quote calls after screener (PreMarketMoversWidget fetches directly)
 *   - watchlist   : requires S1 member lookup (WatchlistMoversWidget fetches directly)
 *
 * DATA SOURCE: GET /v1/dashboard/snapshot (S9 composition endpoint, PLAN-0070 C-2)
 */
export interface DashboardSnapshotResponse {
  /** Top 8 ranked articles from S6 nlp-pipeline. */
  news: RankedNewsResponse | null;
  /** GICS sector heatmap from S3 market-data (11 sectors, 1D returns). */
  heatmap: MarketHeatmapResponse | null;
  /**
   * Top 5 prediction markets from S3 market-data.
   * WHY items (not markets): S3's PredictionMarketsListResponse uses `items`
   * — the TypeScript PredictionMarketsResponse uses `markets`. The wire carries
   * `items`; this type reflects what the API actually returns.
   */
  prediction_markets: { items: PredictionMarket[]; total: number } | null;
  /** Upcoming 7-day company earnings from S7 knowledge-graph. */
  earnings_calendar: EarningsCalendarResponse | null;
  /** Top 10 pending alerts from S10 alert service. */
  alerts: AlertsResponse | null;
  /** AI-generated morning brief from S8 rag-chat. */
  morning_brief: BriefingResponse | null;
  /** Server-side metadata: partial=true when ≥1 leg failed. */
  _meta?: { partial: boolean; legs_failed: number };
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

// ── Feedback subsystem (PLAN-0053 Wave G) ─────────────────────────────────
//
// WHY THIS LIVES HERE: Mirrors the Pydantic schemas declared in
// services/portfolio/src/portfolio/api/feedback_schemas.py. The gateway
// serialises/deserialises these directly — every field name and union
// member matches the backend. If you change a value here, change the
// backend at the same time.
//
// SECURITY: `console_logs` is `unknown` (not `any`) so consumers must
// narrow before reading. The backend redacts secrets server-side; the UI
// must NEVER display raw `console_logs` without sanitising further.

/** Feedback kind — must match backend Literal in feedback_schemas.py. */
export type FeedbackKind = "bug" | "feature_request" | "ux" | "design" | "other";

/** Severity bucket for bug reports — null for non-bug submissions. */
export type FeedbackSeverity = "low" | "medium" | "high" | "critical";

/** Lifecycle status of a feedback submission (admin-managed). */
export type FeedbackStatus =
  | "open"
  | "triaged"
  | "in_progress"
  | "resolved"
  | "closed"
  | "duplicate";

/** Lifecycle status of a feature request (public roadmap). */
export type FeatureStatus =
  | "proposed"
  | "planned"
  | "in_progress"
  | "shipped"
  | "rejected";

/** Micro-survey reaction enum — matches backend SurveyResponse Literal. */
export type SurveyResponse = "positive" | "negative" | "neutral";

/**
 * FeedbackSubmission — full server-side shape for `/v1/feedback/submissions`.
 *
 * WHY user_id can be null: anonymous submissions are allowed (the user
 * supplies an `email` instead). See PRD audit Section 5: "Open Question 2 —
 * Anonymous submissions allowed (with email)".
 */
export interface FeedbackSubmission {
  id: string;
  tenant_id: string;
  user_id: string | null;
  email: string | null;
  kind: FeedbackKind;
  severity: FeedbackSeverity | null;
  description: string;
  // WHY unknown (not any): the backend stores arbitrary JSON-serialisable
  // log entries. Consumers must explicitly narrow before rendering.
  console_logs: unknown | null;
  screenshot_url: string | null;
  page_url: string | null;
  user_agent: string | null;
  status: FeedbackStatus;
  tags: string[];
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

/** Request body shape for POST /v1/feedback/submissions. */
export interface FeedbackSubmissionPayload {
  kind: FeedbackKind;
  severity?: FeedbackSeverity | null;
  /** Required: 10-5000 chars (enforced by backend Pydantic validator). */
  description: string;
  console_logs?: unknown;
  screenshot_url?: string | null;
  email?: string | null;
  page_url?: string | null;
  user_agent?: string | null;
}

/** Admin-only PATCH body — partial update of mutable fields. */
export interface FeedbackSubmissionUpdate {
  status?: FeedbackStatus;
  tags?: string[];
  assigned_to?: string | null;
}

/** Filters for GET /v1/feedback/submissions. */
export interface FeedbackSubmissionFilters {
  /** When true: list ONLY the caller's own submissions (user-facing view). */
  mine?: boolean;
  status?: FeedbackStatus;
  kind?: FeedbackKind;
  limit?: number;
  offset?: number;
}

/** Backend list-response wrapper — matches FeedbackListResponse Pydantic schema. */
export interface FeedbackListResponse {
  items: FeedbackSubmission[];
  total: number;
}

/** NPS submission record returned by POST /v1/feedback/nps. */
export interface NPSScore {
  id: string;
  score: number;
  created_at: string;
}

/** Body of POST /v1/feedback/nps. */
export interface NPSPayload {
  /** 0-10 inclusive (backend rejects out-of-range). */
  score: number;
  comment?: string | null;
  /** Trigger surface tag for analytics ("post_sync", "post_first_alert", …). */
  surface?: string | null;
}

/** Aggregate NPS metrics returned by GET /v1/feedback/nps/aggregate (admin-only). */
export interface NPSAggregate {
  promoter_count: number;
  passive_count: number;
  detractor_count: number;
  /** -100..100 standard NPS formula = %promoters - %detractors. */
  nps_score: number;
  sample_size: number;
  period_days: number;
}

/** Feature-request shape — matches FeatureRequestResponse Pydantic schema. */
export interface FeatureRequest {
  id: string;
  title: string;
  description: string;
  status: FeatureStatus;
  category: string | null;
  vote_count: number;
  is_public: boolean;
  created_at: string;
  updated_at: string;
  /** Per-viewer flag — `true` if the current user has voted on this row. */
  has_voted: boolean;
}

/** Body of POST /v1/feedback/features. */
export interface FeatureRequestPayload {
  /** 1-200 chars. */
  title: string;
  /** 1-5000 chars. */
  description: string;
  category?: string | null;
}

/** Filters for GET /v1/feedback/features. */
export interface FeatureRequestFilters {
  status?: FeatureStatus;
  category?: string | null;
  limit?: number;
  offset?: number;
}

/** Vote response — current count + viewer's vote state. */
export interface FeatureVoteResponse {
  feature_request_id: string;
  vote_count: number;
  has_voted: boolean;
}

/** Body of POST /v1/feedback/micro-survey. */
export interface MicroSurveyPayload {
  /** Survey identifier — 1-100 chars (e.g. "dashboard_helpful"). */
  survey_key: string;
  response: SurveyResponse;
  /** Optional free-text follow-up — ≤ 2000 chars. */
  comment?: string | null;
}

// ── Beta program enrollment ────────────────────────────────────────────────
//
// PLAN-0052 Wave E T-E-5-07: Backend lives at
//   GET    /v1/feedback/beta-program/enrollment
//   PATCH  /v1/feedback/beta-program/enrollment
// (Proxied through api-gateway.routes.proxy.feedback_*_beta_enrollment.)
//
// The Pydantic model on the backend (api-gateway BetaEnrollmentResponse)
// returns one row keyed on (tenant_id, user_id). When the user has never
// opted in, the route returns the row with `enrolled: false` so the UI can
// render an unchecked toggle without special-casing 404. The PATCH body
// is a single optional field — flip the boolean and the server upserts.

/** Server-side BetaEnrollment row — matches BetaEnrollmentResponse. */
export interface BetaEnrollment {
  /** UUIDv7 — present when the user has ever opted in. */
  id: string | null;
  /** ISO timestamp — null until first enrollment. */
  enrolled_at: string | null;
  /** Whether the user is currently in the beta cohort. */
  enrolled: boolean;
  /**
   * Optional notes the user can leave (e.g. "interested in graph features").
   * ≤ 500 chars. Server stores empty string as NULL.
   */
  notes: string | null;
}

/** PATCH body — partial; server merges any present fields. */
export interface BetaEnrollmentPatch {
  enrolled?: boolean;
  notes?: string | null;
}

// ── Full-text document search (PLAN-0064 W6) ─────────────────────────────────

/**
 * Single search result document from GET /v1/search/documents.
 *
 * WHY match_offsets (not HTML snippet): The backend returns plain text in
 * `snippet` and character offsets where matches occur. The frontend renders
 * `<mark>` tags from these offsets using React's automatic XSS escaping.
 * This avoids any dangerouslySetInnerHTML surface — AD-W6-3 snippet contract.
 *
 * WHY entity_hits is string[] not UUID[]: UUIDs arrive as strings over JSON;
 * the frontend never does arithmetic on them, so parsing to a typed UUID
 * class would waste CPU on every search render.
 */
export interface SearchDocumentResult {
  doc_id: string;
  title: string | null;
  source_type: string;
  source_url: string | null;
  published_at: string | null;  // ISO 8601 UTC
  snippet: string | null;       // plain text, no HTML — see AD-W6-3
  match_offsets: [number, number][];  // [start, end] char offsets in snippet
  score: number;
  entity_hits: string[];  // entity_id UUIDs (as strings) that matched
}

/**
 * Entity facet sidebar item — one entity that appears across the result set.
 *
 * WHY count: lets the sidebar show "Apple Inc. (12)" without re-counting on the
 * client. The backend aggregates entity_mentions per entity_id in the SQL query.
 */
export interface SearchDocumentsFacet {
  entity_id: string;
  name: string;
  entity_type: string;
  count: number;
}

/**
 * Full search response from GET /v1/search/documents.
 *
 * WHY latency_ms: server-side timing lets the frontend show "Found 42 results
 * (120ms)" in the search bar status — a Bloomberg-terminal pattern that signals
 * system health to power users.
 */
export interface SearchDocumentsResponse {
  query: string;
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  results: SearchDocumentResult[];
  facets: SearchDocumentsFacet[];
  latency_ms: number;
}

/**
 * Request params for searchDocuments() — maps to GET /v1/search/documents query params.
 *
 * WHY entity_ids (plural) here but entity_id (singular) in the URL: the backend
 * uses repeated params `entity_id=a&entity_id=b` (FastAPI list[UUID] semantics).
 * The frontend sends them as repeated params; we use the plural name in the TypeScript
 * interface to signal "this is a list". The serialisation in searchDocuments() handles
 * the conversion via `url.append("entity_id", ...)`.
 *
 * WHY all optional except q: defaults match the backend: scope="all", source_type="all",
 * page=1, page_size=25. The frontend only needs to pass overrides.
 */
export interface SearchDocumentsParams {
  q: string;
  entity_ids?: string[];
  scope?: "watchlist" | "portfolio" | "all";
  source_type?: "news" | "sec_edgar" | "all";
  // NOTE: "transcript" is intentionally absent from source_type — not yet ingested.
  date_from?: string;  // ISO 8601 date string (timezone-aware on backend)
  date_to?: string;
  date_preset?: "since_last_visit" | "7d" | "30d" | "90d";
  page?: number;
  page_size?: number;
}

// ── PLAN-0088 Wave E — Holdings redesign ──────────────────────────────────────

/**
 * HoldingLotItem — one open FIFO lot for a single holding.
 *
 * Surfaced inside the holdings-table expand-row. Each lot has the
 * acquisition date, remaining quantity, fee-adjusted cost-per-share, the
 * calendar-day holding period, the ST/LT tax classification (>365 days),
 * and an optional unrealised P&L (only present when the gateway supplied
 * a current_price).
 *
 * WHY decimals are numbers here (not strings): the lib/api/portfolios.ts
 * gateway adapter parses S1's 8-dp decimal strings to JS numbers at the
 * boundary so React components can do arithmetic without re-parsing on
 * every render. See the same pattern for HoldingsResponse.
 */
export interface HoldingLotItem {
  open_date: string;          // ISO date "YYYY-MM-DD"
  qty: number;
  cost_per_share: number;
  days_held: number;
  is_long_term: boolean;
  unrealised_pnl: number | null;
}

/**
 * HoldingLotsResponse — payload of GET /v1/portfolios/{id}/holdings/{instrument_id}/lots.
 *
 * Lots are oldest-first (FIFO order). Header summary fields let the UI
 * render a "8 ST / 12 LT" caption above the lot table without iterating
 * the lots client-side.
 */
export interface HoldingLotsResponse {
  portfolio_id: string;
  instrument_id: string;
  lots: HoldingLotItem[];
  total_qty: number;
  total_cost: number;
  long_term_qty: number;
  short_term_qty: number;
  /** UTC ISO-8601 timestamp the lots were materialised. */
  as_of: string;
}

/**
 * TopPositionItem — one row of the top-N positions list.
 *
 * weight_pct is in the 0-100 percent scale (NOT a fraction) so the strip
 * can render "33.4%" by appending a '%' without scaling. Matches the HHI
 * convention used everywhere else in the response.
 */
export interface TopPositionItem {
  instrument_id: string;
  weight_pct: number;
}

/**
 * ConcentrationResponse — payload of GET /v1/portfolios/{id}/concentration.
 *
 * `hhi` is the Herfindahl-Hirschman index in the standard 0-10,000 scale;
 * `label` is one of "diversified" | "moderate" | "concentrated" | "empty".
 * `prices_stale` is the same flag the exposure endpoint emits — frontend
 * shows a small caveat icon when true so the user knows the row is computed
 * on cost basis.
 */
export interface ConcentrationResponse {
  portfolio_id: string;
  hhi: number;
  label: "diversified" | "moderate" | "concentrated" | "empty";
  top_3_share_pct: number;
  positions_count: number;
  top_positions: TopPositionItem[];
  prices_stale: boolean;
}
