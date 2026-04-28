/**
 * lib/gateway.ts — Typed S9 API Gateway client
 *
 * WHY THIS EXISTS: Single module for all S9 API calls from the frontend.
 * Components NEVER call fetch() directly — they use this gateway.
 * Benefits:
 * 1. Type safety: each method returns a typed Promise<T>
 * 2. Auth centralised: token header added in one place
 * 3. Error handling: one location to handle 401 refresh, 500 retry, etc.
 * 4. Testability: mock gateway.ts in tests, not fetch() globally
 *
 * WHO USES IT: TanStack Query queryFn callbacks in all feature components.
 * Usage: const { data } = useQuery({ queryFn: () => gw.getPortfolios() })
 *        where gw = createGateway(accessToken)
 *
 * DATA SOURCE: All calls go to /api/* which next.config.ts rewrites to
 * API_GATEWAY_URL (S9 FastAPI at localhost:8000 in dev).
 *
 * DESIGN REFERENCE: docs/specs/0028-worldview-web-frontend.md §6.2
 * SECURITY: Access token NEVER stored in localStorage — passed as parameter.
 *           Token is in React state (AuthContext) only.
 */

import type {
  AuthCallbackResponse,
  WsTokenResponse,
  CompanyOverview,
  OHLCVResponse,
  Quote,
  BatchQuoteResponse,
  Fundamentals,
  FundamentalsSectionResponse,
  FundamentalsTimeseriesResponse,
  EntityGraph,
  ContradictionsResponse,
  NewsResponse,
  RankedNewsResponse,
  TopNewsParams,
  EntityNewsParams,
  ScreenerField,
  ScreenerRequest,
  ScreenerResponse,
  Portfolio,
  Holding,
  HoldingsResponse,
  TransactionsResponse,
  TransactionRequest,
  Transaction,
  Watchlist,
  WatchlistMember,
  AlertsResponse,
  Thread,
  ChatStreamRequest,
  PredictionMarket,
  PredictionMarketsResponse,
  EconomicCalendarResponse,
  MarketHeatmapResponse,
  TopMoversResponse,
  SearchResult,
  SearchResponse,
  AiSignalsResponse,
  BriefingResponse,
  PaginationParams,
  BrokerageConnection,
  InitiateBrokerageConnectionResponse,
  SyncError,
  // PLAN-0046 Wave 5 — analytics
  ValueHistoryResponse,
  ExposureResponse,
  RiskMetricsResponse,
} from "@/types/api";

// ── Base URL ──────────────────────────────────────────────────────────────

/**
 * All API calls use the /api prefix, which next.config.ts rewrites to S9.
 * No port numbers, no service names — always /api/v1/...
 */
const BASE = "/api";

// ── Internal fetch wrapper ────────────────────────────────────────────────

/**
 * apiFetch — wrapper around fetch() with:
 * - Authorization header injection
 * - JSON response parsing
 * - Error response handling (throws GatewayError for non-2xx)
 *
 * WHY a custom error: GatewayError includes status code so callers can
 * distinguish 401 (re-auth needed) from 503 (service down).
 */
export class GatewayError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "GatewayError";
  }
}

interface FetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  token?: string;
}

async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const { body, token, ...rest } = options;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(rest.headers as Record<string, string> | undefined),
  };

  // WHY token in Authorization header (not cookie):
  // The access token lives in React state (AuthContext).
  // We pass it as Bearer token per standard OAuth2 (PRD-0025 §8).
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE}${path}`, {
    ...rest,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    // Try to get error detail from JSON response body
    let detail = response.statusText;
    try {
      const errorBody = await response.json() as { detail?: string };
      detail = errorBody.detail ?? detail;
    } catch {
      // Response body not JSON — use statusText
    }
    throw new GatewayError(response.status, detail);
  }

  // Handle 204 No Content (e.g., DELETE endpoints)
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}

// ── Response transformation helpers ───────────────────────────────────────
//
// WHY helpers outside the factory: These pure functions are used by multiple gateway
// methods (getWatchlists, getWatchlist, createWatchlist). Extracting them avoids
// duplication and makes the field mappings testable in isolation if needed.

/**
 * mapRawWatchlist — transform S1's WatchlistResponse into the frontend Watchlist type
 *
 * S1 returns: { id, tenant_id, user_id, name, status, created_at }
 * Frontend expects: { watchlist_id, name, owner_id, members, member_count, created_at, updated_at }
 *
 * Key differences:
 * - `id` → `watchlist_id` (domain naming convention)
 * - `user_id` → `owner_id` (frontend uses owner_id for consistency with Portfolio)
 * - `updated_at` defaults to `created_at` (S1 does not track updated_at on watchlists)
 *
 * PLAN-0046 / BP-265 — historical bug: this mapper used to hard-code
 *   `members: []`. That silently masked the missing `GET /watchlists/{id}/members`
 *   endpoint and made the tab look empty even when symbols had been added. Lesson:
 *   collections returned by gateway mappers must always come from a real fetch —
 *   defaulting to `[]` because "we don't have it yet" hides the gap. Callers
 *   pass the real members in via the optional `members` argument; if undefined
 *   we still default to [] but only to support the create/rename payloads which
 *   genuinely don't include members. List flows MUST resolve members before
 *   handing off to the UI.
 */
function mapRawWatchlist(
  raw: {
    id: string;
    tenant_id: string;
    user_id: string;
    name: string;
    status: string;
    created_at: string;
  },
  members?: WatchlistMember[],
): Watchlist {
  // WHY ?? not ||: explicit `[]` from the caller (an empty watchlist) is a
  // real value and must NOT be replaced with another empty array. Only
  // `undefined` (no caller-supplied members) falls through to the default.
  const resolvedMembers = members ?? ([] as WatchlistMember[]);
  return {
    watchlist_id: raw.id,
    name: raw.name,
    owner_id: raw.user_id,
    members: resolvedMembers,
    member_count: resolvedMembers.length,
    created_at: raw.created_at,
    updated_at: raw.created_at, // S1 has no updated_at; use created_at as fallback
  };
}

// ── Gateway factory ───────────────────────────────────────────────────────

/**
 * createGateway — creates a typed gateway instance bound to an access token
 *
 * WHY factory (not singleton): The access token changes on refresh.
 * Components call this inside TanStack Query's queryFn closure where they
 * have access to the latest token from useAuth():
 *
 *   const { accessToken } = useAuth()
 *   const { data } = useQuery({
 *     queryKey: ["portfolios"],
 *     queryFn: () => createGateway(accessToken).getPortfolios()
 *   })
 *
 * The queryFn re-runs on refetch, always using the latest token.
 */
export function createGateway(token?: string | null) {
  const t = token ?? undefined;

  return {
    // ── Auth ─────────────────────────────────────────────────────────

    /**
     * exchangeCode — PKCE token exchange with S9
     *
     * WHY POST (not GET): The code_verifier is sensitive (it proves ownership of
     * the code_challenge sent during authorization). GET params appear in server
     * logs, proxy logs, and browser history. POST body is not logged or cached.
     *
     * WHY S9 handles the exchange (not direct Zitadel): S9 calls Zitadel's token
     * endpoint server-to-server, sets the httpOnly refresh cookie, and returns
     * only the access token to the browser. The refresh token never touches
     * browser-side JS — it stays in the httpOnly cookie (XSS-safe).
     */
    exchangeCode(params: {
      code: string;
      code_verifier: string;
      redirect_uri: string;
    }): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/callback", {
        method: "POST",
        body: params,
      });
    },

    /**
     * refreshToken — silent token refresh using httpOnly refresh token cookie
     * Called by AuthContext on 401 responses and on app mount
     */
    refreshToken(): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/refresh", {
        method: "POST",
        token: t,
      });
    },

    /**
     * logout — revoke refresh token and clear cookie
     */
    logout(): Promise<void> {
      return apiFetch<void>("/v1/auth/logout", {
        method: "POST",
        token: t,
      });
    },

    /**
     * getWsToken — get short-lived (30s) WebSocket auth token
     * Called by useAlertStream immediately before opening the WS connection.
     * The WS token goes in ?token= on the WS URL (browsers can't set WS headers).
     */
    getWsToken(): Promise<WsTokenResponse> {
      return apiFetch<WsTokenResponse>("/v1/auth/ws-token", { token: t });
    },

    /**
     * devLogin — skip Zitadel entirely; get a demo JWT from S9
     *
     * WHY THIS EXISTS: During local development, Zitadel is often not running.
     * S9 exposes POST /v1/auth/dev-login ONLY when OIDC discovery was skipped
     * (oidc_config=None). This endpoint returns the same shape as the real
     * callback response so AuthContext.setTokens() works identically.
     *
     * SECURITY: Returns 403 in production (where OIDC config IS loaded).
     * This method is only called by the login page "Dev Login" button.
     */
    devLogin(): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/dev-login", {
        method: "POST",
      });
    },

    // ── Instruments / Market Data ─────────────────────────────────────

    /**
     * getCompanyOverview — composite response: fundamentals + OHLCV + news
     * Used by Instrument Detail page for the initial page load
     */
    getCompanyOverview(instrumentId: string): Promise<CompanyOverview> {
      return apiFetch<CompanyOverview>(
        `/v1/companies/${encodeURIComponent(instrumentId)}/overview`,
        { token: t },
      );
    },

    /**
     * getOHLCV — candlestick bars for lightweight-charts
     * timeframe: "5M" | "1H" | "1D" | "1W" | "1M" (frontend convention: uppercase)
     *
     * WHY transform: S3 market-data returns OHLCVListResponse with `items` (not `bars`),
     * `bar_date` (not `timestamp`), and string OHLCV values (not numbers). The frontend
     * OHLCVBar type expects `timestamp: string` and numeric open/high/low/close. Transform
     * here at the gateway boundary so components stay decoupled from S3's schema.
     *
     * WHY lowercase timeframe before sending: S3 accepts "1d"/"1h"/"5m"/"1w" (lowercase)
     * BUT "1M" (uppercase M) for monthly — S3's Timeframe.ONE_MONTH = "1M" is
     * case-sensitive. Simple toLowerCase() would produce "1m" which S3 rejects.
     * The chart sends "5M"/"1H"/"1D"/"1W"/"1M" (uppercase frontend convention).
     * Normalize here so S3 doesn't return 422.
     */
    async getOHLCV(
      instrumentId: string,
      params: { timeframe?: string; start?: string; end?: string } = {},
    ): Promise<OHLCVResponse> {
      // WHY special-case "1M": S3's Timeframe enum is case-sensitive.
      // All timeframes are lowercase EXCEPT ONE_MONTH which is "1M" (uppercase M).
      // Frontend sends "1M" (its own uppercase convention), which happens to match
      // S3's expected casing — so we preserve it. Everything else lowercases normally.
      const normalizeTimeframe = (tf: string): string =>
        tf === "1M" ? "1M" : tf.toLowerCase();

      const normalized = {
        ...params,
        ...(params.timeframe ? { timeframe: normalizeTimeframe(params.timeframe) } : {}),
      };
      const qs = new URLSearchParams(
        Object.entries(normalized).filter(([, v]) => v != null) as [string, string][],
      ).toString();

      // WHY raw type: apiFetch would cast to OHLCVResponse directly, bypassing transform
      const raw = await apiFetch<{
        items: Array<{
          bar_date: string;
          open: string;
          high: string;
          low: string;
          close: string;
          volume: number | null;
        }>;
        total: number;
        timeframe: string;
      }>(`/v1/ohlcv/${encodeURIComponent(instrumentId)}${qs ? `?${qs}` : ""}`, { token: t });

      return {
        instrument_id: instrumentId,
        ticker: "",
        // Keep the frontend's uppercase convention in the response
        timeframe: (params.timeframe ?? "1D").toUpperCase(),
        bars: (raw.items ?? []).map((item) => ({
          timestamp: item.bar_date,
          open: parseFloat(item.open),
          high: parseFloat(item.high),
          low: parseFloat(item.low),
          close: parseFloat(item.close),
          volume: item.volume ?? 0,
        })),
      };
    },

    /**
     * getQuote — live quote for a single instrument (5s Valkey cache on S9)
     */
    getQuote(instrumentId: string): Promise<Quote> {
      return apiFetch<Quote>(
        `/v1/quotes/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
    },

    /**
     * getBatchQuotes — prices for multiple instruments at once
     * Used by: Sidebar watchlist (30s refetch), Portfolio page, TopBar index tickers
     * Body: { instrument_ids: string[] } — field name matches BatchQuoteRequest Pydantic model
     */
    getBatchQuotes(ids: string[]): Promise<BatchQuoteResponse> {
      return apiFetch<BatchQuoteResponse>("/v1/quotes/batch", {
        method: "POST",
        body: { instrument_ids: ids },
        token: t,
      });
    },

    /**
     * getFundamentals — all fundamental metrics for an instrument
     * Used by Instrument Detail → Fundamentals tab
     */
    getFundamentals(instrumentId: string): Promise<Fundamentals> {
      return apiFetch<Fundamentals>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}`,
        { token: t },
      );
    },

    /**
     * getFundamentalsTimeseries — single-metric time series for sparklines
     *
     * WHY no auth: S9 route /v1/fundamentals/timeseries is a public endpoint —
     * it issues a system JWT internally (not a user JWT). No Bearer token sent.
     *
     * WHY instrument_id + metric as query params (not path): the S3 endpoint
     * is designed as a filter over the fundamentals_metrics table, not a
     * resource path. Multiple instruments or metrics could be fetched with the
     * same route shape.
     *
     * Used by: FundamentalSparkline (Overview sidebar panels + Fundamentals tab inline charts)
     * Default limit of 20 gives enough points for a sparkline without over-fetching.
     */
    getFundamentalsTimeseries(
      instrumentId: string,
      metric: string,
      params?: {
        start_date?: string;
        end_date?: string;
        period_type?: string;
        limit?: number;
        // order: 'asc' returns the oldest N rows, 'desc' returns the most recent N
        // (DESC is what UI charts almost always want — see audit 2026-04-28 / BP-261).
        // Returned data is always chronologically ascending regardless of order.
        order?: "asc" | "desc";
      },
    ): Promise<FundamentalsTimeseriesResponse> {
      // WHY URLSearchParams with conditional spread: filters out undefined values so
      // optional params don't appear as "undefined" strings in the query string.
      const qs = new URLSearchParams({
        instrument_id: instrumentId,
        metric,
        ...(params?.start_date ? { start_date: params.start_date } : {}),
        ...(params?.end_date ? { end_date: params.end_date } : {}),
        ...(params?.period_type ? { period_type: params.period_type } : {}),
        ...(params?.limit != null ? { limit: String(params.limit) } : {}),
        ...(params?.order ? { order: params.order } : {}),
      });
      return apiFetch<FundamentalsTimeseriesResponse>(
        `/v1/fundamentals/timeseries?${qs.toString()}`,
        {}, // no auth — public endpoint uses system JWT internally
      );
    },

    /**
     * getTechnicals — technical indicators snapshot from S3
     *
     * WHY /technicals (not /technicals-snapshot): S9 exposes the shortened path.
     * S3 internally stores this as "technicals_snapshot" section.
     * Used by: TechnicalSnapshot component (Wave D-3), OverviewSidebarMetrics (Wave C-1)
     */
    getTechnicals(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/technicals`,
        { token: t },
      );
    },

    /**
     * getShareStatistics — share count and ownership percentages from S3
     *
     * Data fields: shares_outstanding, shares_float, percent_insiders, percent_institutions.
     * Cast records[0].data to ShareStatisticsData for typed access.
     * Used by: OwnershipSnapshotPanel (Wave D-2)
     */
    getShareStatistics(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/share-statistics`,
        { token: t },
      );
    },

    /**
     * getInsiderTransactions — recent insider buys/sells from S3
     *
     * Returns records with section="insider_transactions_snapshot". Each record's
     * data array contains individual transactions (date, owner_name, type, shares, value).
     * Used by: InsiderTransactionsTable (Wave D-3)
     */
    getInsiderTransactions(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/insider-transactions`,
        { token: t },
      );
    },

    /**
     * getEarningsHistory — historical EPS actuals from S3 (ANNUAL records)
     *
     * WHY /earnings-annual-trend (not /earnings-trend): The S9 /earnings-trend
     * endpoint maps to EODHD's EarningsTrend section which contains FORWARD-LOOKING
     * analyst consensus estimates (period "+1q", "+1y") — not historical actuals.
     * The /earnings-annual-trend endpoint contains historical per-fiscal-year EPS
     * actuals stored as `{date: "YYYY-MM-DD", epsActual: N}` records. This is what
     * analysts need to see the multi-year EPS growth trajectory (the primary input
     * for P/E target valuation). Live data confirms: 33 historical annual EPS records
     * for AAPL from /earnings-annual-trend vs 0 records from the timeseries endpoint.
     * Used by: EarningsHistoryChart (Wave D-3)
     */
    getEarningsHistory(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/earnings-annual-trend`,
        { token: t },
      );
    },

    /**
     * getSplitsDividends — stock split and dividend history from S3
     *
     * Returns records with section="splits_dividends". Contains forward and
     * historical split ratios, dividend dates, and ex-dividend dates.
     * Used by: FundamentalsTab (Wave D-1 splits section), future D-3 enrichment
     */
    getSplitsDividends(instrumentId: string): Promise<FundamentalsSectionResponse> {
      return apiFetch<FundamentalsSectionResponse>(
        `/v1/fundamentals/${encodeURIComponent(instrumentId)}/splits-dividends`,
        { token: t },
      );
    },

    // ── Knowledge Graph ───────────────────────────────────────────────

    /**
     * getEntityGraph — egocentric knowledge graph for sigma.js
     *
     * WHY limit is derived from depth, NOT sent to S7 as depth:
     * S7's GET /api/v1/entities/{id}/graph does NOT have a `depth` param —
     * it only has `limit` (max relations to return, default 50, max 200).
     * The `depth` concept (1-hop vs 2-hop) does NOT exist in S7's SQL query;
     * S7 returns all direct relations up to `limit`.
     *
     * Sending `?depth=2` is silently ignored by S7 (FastAPI discards unknown
     * query params). The graph size is controlled entirely by `limit`.
     *
     * WHY cap by depth level:
     * - depth=1 (compact sidebar SVG in EntityGraphPanel): needs at most 15
     *   relations. More causes visual clutter and N+1 entity lookups in S7's
     *   GetEntityGraphUseCase (one DB round-trip per unique entity in relations).
     * - depth=2 (full sigma.js graph in IntelligenceTab): can absorb more data
     *   but capping at 40 prevents >40 sequential entity fetches in S7.
     *   The sigma.js renderer handles 40 nodes comfortably at 60fps.
     *
     * WHY pass `min_confidence=0.3` for depth=1:
     * Low-confidence edges add visual noise in the compact SVG sidebar.
     * The full Intelligence tab (depth=2) keeps min_confidence=0 to show
     * the full relationship picture.
     *
     * @param entityId - Entity UUID
     * @param depth - Visual depth level: 1 = compact sidebar, 2 = full graph
     */
    getEntityGraph(
      entityId: string,
      depth = 2,
    ): Promise<EntityGraph> {
      // WHY separate limits: depth=1 sidebar has limited visual space (320×280px
      // SVG); fetching more than 15 relations causes N+1 lookups in S7 with no
      // visual benefit. depth=2 uses WebGL sigma.js which handles more nodes.
      const limit = depth === 1 ? 15 : 40;

      // WHY min_confidence for depth=1: sidebar SVG should show only high-quality
      // edges (≥0.3 confidence). The full Intelligence tab shows all edges.
      const minConfidence = depth === 1 ? 0.3 : 0.0;

      const params = new URLSearchParams({
        limit: String(limit),
        min_confidence: String(minConfidence),
      });

      return apiFetch<EntityGraph>(
        `/v1/entities/${encodeURIComponent(entityId)}/graph?${params.toString()}`,
        { token: t },
      );
    },

    /**
     * getContradictions — detected contradictory claims for an entity
     * Used by Instrument Detail → Intelligence tab
     */
    getContradictions(entityId: string): Promise<ContradictionsResponse> {
      return apiFetch<ContradictionsResponse>(
        `/v1/entities/${encodeURIComponent(entityId)}/contradictions`,
        { token: t },
      );
    },

    // ── News ──────────────────────────────────────────────────────────

    /**
     * getTopNews — ranked news feed by composite relevance/impact score (PRD-0026)
     * Used by: Dashboard WatchlistNews, Alerts/News page → Top Today tab
     *
     * WHY no auth: news/top is a public endpoint — no personal data involved.
     * WHY RankedNewsResponse: S6 NLP Pipeline (not S5 Content Store) now serves
     * this endpoint, returning the richer RankedArticle shape with multi-window
     * price impact scores and LLM relevance scores. Proxy retargeted in Wave 7.
     *
     * @param params - TopNewsParams (hours, limit, offset, min_display_score, routing_tier)
     */
    getTopNews(params: TopNewsParams = {}): Promise<RankedNewsResponse> {
      const qs = new URLSearchParams(
        // WHY filter null/undefined: URLSearchParams(undefined) → "undefined" string.
        // This filter ensures only explicitly set params appear in the query string.
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<RankedNewsResponse>(`/v1/news/top${qs ? `?${qs}` : ""}`);
    },

    /**
     * getEntityNews — relevance-scored news articles for a specific entity (PRD-0026)
     * Used by Instrument Detail → News tab
     *
     * WHY RankedNewsResponse: proxy was retargeted from S5 to S6 in Wave 7.
     * S6 returns RankedArticle[] (with source_name, display_relevance_score, etc.)
     * rather than Article[] (source, summary, tickers, sentiment).
     *
     * @param entityId - The entity UUID
     * @param params - EntityNewsParams (start_date, end_date, order_by, limit, offset)
     */
    getEntityNews(
      entityId: string,
      params: EntityNewsParams = {},
    ): Promise<RankedNewsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<RankedNewsResponse>(
        `/v1/news/entity/${encodeURIComponent(entityId)}${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },

    /**
     * getRelevantNews — general relevance-ranked news feed (legacy endpoint)
     * Used by Alerts/News page → Feed tab
     */
    getRelevantNews(limit = 20): Promise<NewsResponse> {
      return apiFetch<NewsResponse>(`/v1/news/relevant?limit=${limit}`);
    },

    // ── Screener ──────────────────────────────────────────────────────

    /**
     * getScreenerFields — available filter fields for the screener UI
     * Cached by S9/S3 for 6h — infrequently changes
     */
    getScreenerFields(): Promise<ScreenerField[]> {
      return apiFetch<ScreenerField[]>("/v1/fundamentals/screen/fields");
    },

    /**
     * runScreener — execute a screener query
     * Used by Screener page filter form
     */
    runScreener(request: ScreenerRequest): Promise<ScreenerResponse> {
      return apiFetch<ScreenerResponse>("/v1/fundamentals/screen", {
        method: "POST",
        body: request,
        token: t,
      });
    },

    // ── Portfolio ─────────────────────────────────────────────────────

    /**
     * getPortfolios — list authenticated user's portfolios
     *
     * WHY transform: S1 returns a paginated envelope `{items: [{id, owner_id, ...}], total, limit, offset}`
     * (PaginatedResponse<PortfolioResponse>) but frontend components expect a flat `Portfolio[]`
     * with `portfolio_id` (not `id`) and an `updated_at` field. The field rename is because the
     * S1 Pydantic schema uses `id` (database convention) while the frontend type uses `portfolio_id`
     * (domain convention from PRD-0027, ADR-F-12: explicit ID naming to avoid ambiguity).
     */
    async getPortfolios(): Promise<Portfolio[]> {
      // Fetch the raw paginated response from S1 (via S9 proxy)
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          tenant_id: string;
          owner_id: string;
          name: string;
          currency: string;
          status: string;
          // PLAN-0046 Wave 3 / T-46-3-04 — kind discriminator from S1.
          // Optional in the type to keep older S9 builds backward-compatible
          // during rollout; once migration 0011 is everywhere this is always set.
          kind?: "manual" | "brokerage" | "root";
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>("/v1/portfolios", { token: t });

      // Transform each S1 PortfolioResponse into the frontend Portfolio type
      return (raw.items ?? []).map((p) => ({
        portfolio_id: p.id,
        name: p.name,
        currency: p.currency,
        owner_id: p.owner_id,
        created_at: p.created_at,
        // WHY default: S1 does not return updated_at on PortfolioResponse (it only has created_at).
        // Use created_at as fallback so components that display "last updated" still render.
        updated_at: p.created_at,
        // Forward the kind discriminator unchanged so the page can sort the ROOT
        // entry first and disable delete on aggregate portfolios.
        kind: p.kind,
      }));
    },

    /**
     * getHoldings — holdings + P&L summary for a portfolio
     *
     * WHY transform: S1 returns a bare `HoldingResponse[]` array (not the wrapped
     * `HoldingsResponse` object the frontend expects). Each S1 holding has `id` (not
     * `holding_id`) and lacks enriched fields like `ticker`, `name`, `current_price`,
     * `unrealised_pnl` etc. — those are computed client-side from batch quotes.
     * The frontend expects `HoldingsResponse = {portfolio_id, holdings: Holding[], total_value, ...}`.
     */
    async getHoldings(portfolioId: string): Promise<HoldingsResponse> {
      // S1 used to return a plain array of HoldingResponse, but PLAN-0046 QA
      // F-011 standardised the shape to the paginated envelope
      // ``{items, total, limit, offset}``. We accept BOTH during the transition
      // window: an old gateway running a pre-F011 portfolio service still
      // works, and a new gateway against a post-F011 service unwraps ``items``.
      type RawHolding = {
        id: string;
        portfolio_id: string;
        instrument_id: string;
        quantity: string; // S1 serialises Decimal as "0.00000000" string
        average_cost: string; // same decimal string format
        currency: string;
        ticker: string | null;       // from instruments table (null if not synced yet)
        name: string | null;         // from instruments table
        entity_id: string | null;    // from instruments table
      };
      const raw = await apiFetch<
        RawHolding[] | { items: RawHolding[]; total: number; limit: number; offset: number }
      >(`/v1/holdings/${encodeURIComponent(portfolioId)}`, { token: t });

      // Normalise both shapes into a flat array. Defensive: a malformed
      // response that isn't an array OR an envelope yields an empty list.
      const items: RawHolding[] = Array.isArray(raw)
        ? raw
        : Array.isArray((raw as { items?: unknown }).items)
          ? (raw as { items: RawHolding[] }).items
          : [];

      // Transform S1 HoldingResponse into frontend Holding type
      const holdings: Holding[] = items.map((h) => ({
        holding_id: h.id,
        portfolio_id: h.portfolio_id,
        instrument_id: h.instrument_id,
        entity_id: h.entity_id ?? "",
        ticker: h.ticker ?? "",
        name: h.name ?? "",
        // WHY parseFloat: S1 serialises Decimal fields as "0.00000000" strings (Pydantic
        // field_serializer for Numeric(18,8)). The frontend expects numbers for arithmetic.
        quantity: parseFloat(h.quantity) || 0,
        average_cost: parseFloat(h.average_cost) || 0,
        // WHY null: These fields are computed client-side from live quote data, not stored in S1.
        current_price: null,
        unrealised_pnl: null,
        unrealised_pnl_pct: null,
        portfolio_weight: null,
      }));

      return {
        portfolio_id: portfolioId,
        holdings,
        // WHY null: P&L totals require live prices which aren't available from S1.
        // The PortfolioPage component computes these after fetching batch quotes.
        total_value: null,
        total_cost: null,
        total_unrealised_pnl: null,
        total_unrealised_pnl_pct: null,
      };
    },

    /**
     * getPortfolioPerformance — period return for a portfolio.
     *
     * WHY composition endpoint (not raw proxy): S9 fetches holdings from S1 and
     * OHLCV bars from S3, then computes the weighted portfolio return. The frontend
     * cannot safely call two backend services due to CORS and auth constraints.
     *
     * Returns `covered_pct` (0-1) so the UI can show "~" prefix when < 100% of
     * positions have market data available (e.g., new tickers not yet ingested).
     */
    async getPortfolioPerformance(
      portfolioId: string,
      period: "1D" | "1W" | "1M",
    ): Promise<{
      portfolio_id: string;
      period: string;
      return_pct: number;
      return_abs: number;
      covered_pct: number;
    }> {
      const t = token ?? undefined;
      return apiFetch<{
        portfolio_id: string;
        period: string;
        return_pct: number;
        return_abs: number;
        covered_pct: number;
      }>(`/v1/portfolios/${encodeURIComponent(portfolioId)}/performance?period=${period}`, { token: t });
    },

    // ── PLAN-0046 Wave 5 — analytics endpoints ────────────────────────

    /**
     * getValueHistory — equity-curve data for a portfolio.
     *
     * WHY transform: S1 serialises Decimal fields as 8-dp strings (matches
     * every other Decimal in the API). The frontend chart needs numeric
     * values so it can compute `min`, `max`, deltas — convert at the
     * gateway boundary (BP-265 awareness: never default to []; use real
     * fetched data).
     *
     * @param portfolioId resolved portfolio UUID
     * @param params from/to ISO dates (defaults applied server-side: 90d
     *   look-back, today inclusive); granularity = 1d / 1w / 1m
     */
    async getValueHistory(
      portfolioId: string,
      params: {
        from?: string;
        to?: string;
        // F-202 (QA iter-2): server now accepts ``days=N`` as an alias for
        // ``from = today - N``. The frontend uses ``days`` for fixed-period
        // toggles and omits it for "All".
        days?: number;
        granularity?: "1d" | "1w" | "1m";
      } = {},
    ): Promise<ValueHistoryResponse> {
      const qs = new URLSearchParams({
        ...(params.from ? { from: params.from } : {}),
        ...(params.to ? { to: params.to } : {}),
        ...(params.days != null ? { days: String(params.days) } : {}),
        ...(params.granularity ? { granularity: params.granularity } : {}),
      }).toString();
      const path =
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/value-history` +
        (qs ? `?${qs}` : "");
      const raw = await apiFetch<{
        points: Array<{
          date: string;
          value: string;
          cost_basis: string;
          cash: string;
          // F-501 (QA iter-5): per-point data-quality flag. Optional on the
          // wire for forward-compat — older S1 builds omit it.
          data_quality?: string;
        }>;
        // F-009 (QA iter-2): empty-state hint metadata. Optional on the wire
        // for forward compat — older S1 builds don't emit it.
        metadata?: {
          last_snapshot_at: string | null;
          next_scheduled_run_utc: string | null;
        };
      }>(path, { token: t });
      // BP-265 awareness: only default `points` to [] when the server
      // genuinely omitted it (defensive); otherwise pass through what
      // we got, parsed.
      const points = (raw.points ?? []).map((p) => ({
        date: p.date,
        value: parseFloat(p.value),
        cost_basis: parseFloat(p.cost_basis),
        cash: parseFloat(p.cash),
        // F-501: default to "ok" when the server didn't emit the field so
        // downstream consumers (EquityCurveChart tooltip) can do strict
        // string comparisons without null-checking everywhere.
        data_quality: p.data_quality ?? "ok",
      }));
      // Map metadata through unchanged — undefined defaults survive so the
      // chart's empty-state code can null-check the field directly.
      return {
        points,
        metadata: raw.metadata
          ? {
              last_snapshot_at: raw.metadata.last_snapshot_at ?? null,
              next_scheduled_run_utc: raw.metadata.next_scheduled_run_utc ?? null,
            }
          : undefined,
      };
    },

    /**
     * getExposure — current invested / cash / leverage breakdown.
     *
     * S1 returns Decimal-as-string; we parseFloat for chart arithmetic.
     * Empty portfolio → all zeros (NOT NaN — see use case docstring).
     */
    async getExposure(portfolioId: string): Promise<ExposureResponse> {
      const raw = await apiFetch<{
        invested: string;
        cash: string;
        gross_exposure_pct: string;
        net_exposure_pct: string;
        leverage: string;
        // F-016 (QA 2026-04-28): two new optional fields. Older S1 builds
        // omit them entirely; the spread below treats undefined as
        // "not stale" so the UI renders no badge.
        prices_stale?: boolean;
        prices_as_of?: string | null;
      }>(`/v1/portfolios/${encodeURIComponent(portfolioId)}/exposure`, { token: t });
      return {
        invested: parseFloat(raw.invested),
        cash: parseFloat(raw.cash),
        gross_exposure_pct: parseFloat(raw.gross_exposure_pct),
        net_exposure_pct: parseFloat(raw.net_exposure_pct),
        leverage: parseFloat(raw.leverage),
        prices_stale: raw.prices_stale ?? false,
        prices_as_of: raw.prices_as_of ?? null,
      };
    },

    /**
     * getRiskMetrics — drawdown / vol / Sharpe / Sortino / beta vs SPY.
     *
     * WHY no transform: this is a pure S9 *composition* endpoint — every
     * field is already a `number | null` JSON-native value. The strip
     * component renders `null` as "—" so we don't need to coerce.
     */
    getRiskMetrics(
      portfolioId: string,
      lookbackDays = 90,
    ): Promise<RiskMetricsResponse> {
      const qs = new URLSearchParams({ lookback_days: String(lookbackDays) }).toString();
      return apiFetch<RiskMetricsResponse>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}/risk-metrics?${qs}`,
        { token: t },
      );
    },

    /**
     * getTransactions — paginated transaction history
     *
     * WHY transform: S1 returns `PaginatedResponse<TransactionListItem>` = `{items: [...], total, limit, offset}`
     * where each item has `id` (not `transaction_id`) and uses `transaction_type` + `direction` fields
     * instead of the frontend's single `type: "BUY" | "SELL"`. The S9 proxy forwards query params
     * to S1 unchanged, but S1 actually expects `portfolio_id` as query param plus limit/offset.
     * The S1 route reads portfolio_id from the X-Portfolio-ID header, but the S9 proxy passes
     * it as a query parameter — so the S1 handler may fail. For now we pass it as query param
     * since that's what the S9 proxy forwards.
     */
    async getTransactions(
      portfolioId: string,
      params: PaginationParams = {},
    ): Promise<TransactionsResponse> {
      const qs = new URLSearchParams({
        portfolio_id: portfolioId,
        ...(params.limit != null ? { limit: String(params.limit) } : {}),
        ...(params.offset != null ? { offset: String(params.offset) } : {}),
      }).toString();

      // S1 returns PaginatedResponse<TransactionListItem>
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          portfolio_id: string;
          instrument_id: string;
          transaction_type: string;
          direction: string;
          quantity: string; // Decimal serialised as string
          price: string;
          fees: string;
          // PLAN-0046 / BP-263: S1 now returns the broker-reported cash amount
          // for transactions. It is a string (Decimal serialized) when present
          // and null when the broker omitted it or the row pre-dates Alembic
          // migration 0009. The DIVIDEND row total comes from this field.
          amount: string | null;
          currency: string;
          // F-205 (QA iter-2): S1 now populates ``ticker`` and ``name`` server-side
          // via a JOIN to the local instruments table. Both are nullable when the
          // instrument hasn't been synced yet.
          ticker: string | null;
          name: string | null;
          executed_at: string;
          external_ref: string | null;
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(`/v1/transactions?${qs}`, { token: t });

      // Transform S1 TransactionListItem into frontend Transaction type
      const transactions: Transaction[] = (raw.items ?? []).map((tx) => {
        // WHY two fields exist: S1's TransactionType is the "what" (BUY / SELL /
        // DIVIDEND / DEPOSIT / WITHDRAWAL / FEE) and TransactionDirection is the
        // "asset flow" (INFLOW = position increased, OUTFLOW = position decreased).
        // The frontend Transaction.type union is the user-facing label: BUY | SELL | DIVIDEND.
        // BP-261 (2026-04-28): the previous mapping read tx.direction.toUpperCase() and
        // produced literal "INFLOW"/"OUTFLOW" strings — never matching the BUY/SELL filter
        // buttons and breaking the DIVIDEND code-path entirely.
        const txType = (tx.transaction_type ?? "").toUpperCase();
        const txDir = (tx.direction ?? "").toUpperCase();
        // Resolution order, defensive across adapter variants:
        // 1. transaction_type === DIVIDEND → DIVIDEND (income event)
        // 2. transaction_type or direction in {BUY, SELL} → use it directly
        //    (some payloads label direction as BUY/SELL rather than INFLOW/OUTFLOW)
        // 3. direction === INFLOW → BUY; OUTFLOW → SELL (canonical S1 enum)
        // 4. fallback SELL — never emit raw INFLOW/OUTFLOW literals
        const mappedType: Transaction["type"] =
          txType === "DIVIDEND"
            ? "DIVIDEND"
            : txType === "BUY" || txDir === "BUY" || txDir === "INFLOW"
              ? "BUY"
              : txType === "SELL" || txDir === "SELL" || txDir === "OUTFLOW"
                ? "SELL"
                : "SELL";
        return ({
        transaction_id: tx.id,
        portfolio_id: tx.portfolio_id,
        instrument_id: tx.instrument_id,
        // F-205 (QA iter-2): map server-side ticker through. Empty string is
        // the safe display value when the instruments cache miss left it null
        // (matches the previous BP-262 fallback so the table doesn't render
        // a literal "null"). Older S1 builds that don't yet emit the field
        // give us undefined → empty string for the same reason.
        ticker: tx.ticker ?? "",
        type: mappedType,
        quantity: parseFloat(tx.quantity) || 0,
        price: parseFloat(tx.price) || 0,
        fee: parseFloat(tx.fees) || 0,
        // PLAN-0046 / BP-263: map broker-reported amount through to the UI.
        // Strict null preservation — null on the wire stays null, not 0 — so the
        // table can distinguish "broker didn't tell us" from "amount is $0".
        amount: tx.amount != null ? Number(tx.amount) : null,
        currency: tx.currency,
        executed_at: tx.executed_at,
        notes: tx.external_ref,
      });
      });

      return {
        transactions,
        total: raw.total,
        offset: raw.offset,
        limit: raw.limit,
      };
    },

    /**
     * createPortfolio — create a new manually-managed portfolio
     *
     * WHY this exists: Users without a brokerage connection need a way to create a portfolio
     * manually before they can add positions. S9's POST /v1/portfolios proxy injects
     * owner_user_id from the JWT so the frontend only sends name + currency.
     *
     * WHY transform: S1 returns `PortfolioResponse` with `id` (not `portfolio_id`) and no
     * `updated_at` field — same mapping as getPortfolios(). We reuse the same shape.
     *
     * @param name     - Portfolio display name (e.g., "My Main Portfolio")
     * @param currency - 3-letter ISO currency code (default: "USD")
     */
    async createPortfolio(name: string, currency = "USD"): Promise<Portfolio> {
      // POST to S9, which injects owner_user_id from JWT before forwarding to S1
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        owner_id: string;
        name: string;
        currency: string;
        status: string;
        created_at: string;
      }>("/v1/portfolios", {
        method: "POST",
        // WHY omit owner_user_id: S9's create_portfolio proxy reads it from the
        // verified JWT and injects it server-side. Sending it from the client would
        // be a security risk (client could supply any user_id).
        body: { name, currency },
        token: t,
      });

      // Map S1's PortfolioResponse (id) → frontend Portfolio type (portfolio_id)
      return {
        portfolio_id: raw.id,
        name: raw.name,
        currency: raw.currency,
        owner_id: raw.owner_id,
        created_at: raw.created_at,
        updated_at: raw.created_at, // S1 has no updated_at; use created_at as fallback
      };
    },

    /**
     * deletePortfolio — delete a non-root portfolio.
     *
     * F-013 (QA 2026-04-28): added so the new Delete button on the
     * portfolio page can wire up. The S9 proxy forwards to S1 which
     * archives the portfolio (soft delete) and rejects ROOT portfolios
     * with 400 + RootPortfolioNotArchivableError. The frontend disables
     * the button for root, so under normal flow only manual/brokerage
     * portfolios end up here.
     */
    deletePortfolio(portfolioId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/portfolios/${encodeURIComponent(portfolioId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * addPosition — open a new long position by recording a BUY transaction
     *
     * WHY use addTransaction under the hood: S1 has no dedicated "add holding" endpoint.
     * Holdings are derived from transaction history — a BUY transaction creates/increases
     * a holding, a SELL reduces it. To manually open a position, we record a BUY.
     *
     * WHY instrument_id (not ticker): S1's RecordTransactionRequest requires instrument_id
     * (the UUID stored in S3). The caller must resolve ticker → instrument_id first using
     * searchInstruments(). This function expects the resolved UUID.
     *
     * @param portfolioId  - UUID of the portfolio to add the position to
     * @param instrumentId - UUID of the instrument (resolved from ticker via searchInstruments)
     * @param quantity     - Number of shares to add (must be > 0)
     * @param averageCost  - Average cost per share (price at which you bought)
     */
    async addPosition(
      portfolioId: string,
      instrumentId: string,
      quantity: number,
      averageCost: number,
    ): Promise<Transaction> {
      // Holdings in S1 are derived from transactions — a BUY creates/grows a holding.
      // We map the S1 RecordTransactionRequest shape directly (same as addTransaction).
      const s1Body = {
        portfolio_id: portfolioId,
        instrument_id: instrumentId,
        // WHY TRADE + BUY: S1 uses two separate fields for what the frontend combines as "type".
        // transaction_type=TRADE covers manual equity purchases (vs DIVIDEND, FEE, TRANSFER).
        // direction=BUY increases the holding; direction=SELL decreases it.
        transaction_type: "TRADE",
        direction: "BUY",
        quantity,
        price: averageCost,
        fees: 0,                               // manual entry has no brokerage fee
        currency: "USD",                       // default; S1 stores per-transaction currency
        executed_at: new Date().toISOString(), // "now" is the correct timestamp for manual add
        external_ref: null,
      };

      const raw = await apiFetch<{
        id: string;
        portfolio_id: string;
        instrument_id: string;
        transaction_type: string;
        direction: string;
        quantity: string;
        price: string;
        fees: string;
        currency: string;
        executed_at: string;
        created_at: string;
      }>("/v1/transactions", {
        method: "POST",
        body: s1Body,
        token: t,
      });

      return {
        transaction_id: raw.id,
        portfolio_id: raw.portfolio_id,
        instrument_id: raw.instrument_id,
        ticker: "",
        type: "BUY",
        quantity: parseFloat(raw.quantity) || 0,
        price: parseFloat(raw.price) || 0,
        fee: parseFloat(raw.fees) || 0,
        // PLAN-0046 / BP-263: manual entries don't carry a broker amount —
        // the table will fall back to quantity * price for the total.
        amount: null,
        currency: raw.currency,
        executed_at: raw.executed_at,
        notes: null,
      };
    },

    /**
     * addTransaction — record a buy or sell
     *
     * WHY transform: S1's RecordTransactionRequest expects `transaction_type`, `direction`,
     * `fees` (not `fee`), and no `type` field. The S1 response uses `id` (not `transaction_id`).
     * The frontend type uses `type: "BUY"|"SELL"` as a combined field; we need to split it
     * into S1's transaction_type=TRADE + direction=BUY/SELL.
     */
    async addTransaction(tx: TransactionRequest): Promise<Transaction> {
      // Map frontend TransactionRequest to S1's RecordTransactionRequest shape
      const s1Body = {
        portfolio_id: tx.portfolio_id,
        instrument_id: tx.instrument_id,
        // WHY TRADE: S1 distinguishes transaction_type (TRADE, DIVIDEND, FEE, TRANSFER) from
        // direction (BUY, SELL). The frontend only supports manual trades, so always TRADE.
        transaction_type: "TRADE",
        direction: tx.type, // "BUY" or "SELL"
        quantity: tx.quantity,
        price: tx.price,
        fees: tx.fee ?? 0,
        currency: "USD", // Default currency — frontend type doesn't include currency on request
        executed_at: tx.executed_at ?? new Date().toISOString(),
        external_ref: tx.notes ?? null,
      };

      const raw = await apiFetch<{
        id: string;
        portfolio_id: string;
        instrument_id: string;
        transaction_type: string;
        direction: string;
        quantity: string;
        price: string;
        fees: string;
        currency: string;
        executed_at: string;
        created_at: string;
      }>("/v1/transactions", {
        method: "POST",
        body: s1Body,
        token: t,
      });

      return {
        transaction_id: raw.id,
        portfolio_id: raw.portfolio_id,
        instrument_id: raw.instrument_id,
        ticker: "",
        type: raw.direction.toUpperCase() as "BUY" | "SELL",
        quantity: parseFloat(raw.quantity) || 0,
        price: parseFloat(raw.price) || 0,
        fee: parseFloat(raw.fees) || 0,
        // PLAN-0046 / BP-263: manual addTransaction calls do not record an
        // explicit broker `amount`. Stay null to mark "no broker truth".
        amount: null,
        currency: raw.currency,
        executed_at: raw.executed_at,
        notes: null,
      };
    },

    // ── Watchlists ────────────────────────────────────────────────────

    /**
     * getWatchlists — list all watchlists for the authenticated user
     *
     * WHY transform: S1 returns a bare array of `WatchlistResponse` objects with `id`
     * (not `watchlist_id`), `user_id` (not `owner_id`), and NO `members`, `member_count`,
     * or `updated_at` fields. The frontend type `Watchlist` uses domain-named fields and
     * includes member data. The list endpoint intentionally omits members for performance;
     * member data is only fetched when viewing a single watchlist.
     */
    async getWatchlists(): Promise<Watchlist[]> {
      const raw = await apiFetch<
        Array<{
          id: string;
          tenant_id: string;
          user_id: string;
          name: string;
          status: string;
          created_at: string;
        }>
      >("/v1/watchlists", { token: t });

      return (raw ?? []).map((wl) => mapRawWatchlist(wl));
    },

    /**
     * getWatchlist — single watchlist with member list
     *
     * PLAN-0046 / T-46-2-03 — now also fans out to `getWatchlistMembers` so
     * the returned `Watchlist` has a populated `members` array. Without this
     * the consumer of `getWatchlist` would see an empty tab (BP-265).
     *
     * WHY two requests: S1 keeps the watchlist metadata route and the members
     * route separate so the metadata can be cached independently. The cost is
     * one extra round-trip on a relatively cheap endpoint, which is acceptable.
     */
    async getWatchlist(watchlistId: string): Promise<Watchlist> {
      // First fetch the watchlist metadata. We deliberately fire this before
      // the members request so a 404 here short-circuits the second call.
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}`,
        { token: t },
      );

      // Fetch the members in a second call. We do not run these in parallel
      // because if the first 404s we want to skip the second altogether.
      const members = await this.getWatchlistMembers(watchlistId);
      return mapRawWatchlist(raw, members);
    },

    /**
     * getWatchlistMembers — list members of a single watchlist
     *
     * PLAN-0046 / T-46-2-03 — pairs with the new
     * `GET /v1/watchlists/{id}/members` proxied to S1. Returns the raw
     * `WatchlistMember[]` shape used by the UI table; the gateway response
     * already matches the type so we just narrow the cast.
     *
     * WHY a method (not inlined into getWatchlist): the watchlists tab fetches
     * members lazily for the active watchlist only — fetching everyone's
     * members up-front would multiply the round-trips. Exposing this as its
     * own method lets the React component's `useQuery` cache members per
     * watchlist independently from the watchlist list.
     */
    async getWatchlistMembers(watchlistId: string): Promise<WatchlistMember[]> {
      const resp = await apiFetch<{
        members: Array<{
          entity_id: string;
          entity_type: string;
          ticker: string | null;
          name: string | null;
          instrument_id: string | null;
          added_at: string;
          // F-010 (QA 2026-04-28): backend reports "resolved" / "pending"
          // for each member so the UI can render a "resolving…" badge.
          resolution?: "resolved" | "pending";
        }>;
        total: number;
      }>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/members`,
        { token: t },
      );

      // Translate to the frontend `WatchlistMember` shape — `name` is a
      // required string in the type, so coerce nullable backend names to "—".
      // (Backend may return null when the local instrument cache miss
      // happened at add-time; see Alembic 0010 docstring.)
      return (resp.members ?? []).map((m) => ({
        entity_id: m.entity_id,
        instrument_id: m.instrument_id,
        ticker: m.ticker,
        name: m.name ?? "—",
        added_at: m.added_at,
        // Default to "resolved" for older backends that don't yet emit
        // the field — matches the previous behaviour (no badge).
        resolution: m.resolution ?? "resolved",
      }));
    },

    /**
     * createWatchlist — create a new watchlist
     *
     * WHY transform: S1 create returns the same `WatchlistResponse` shape (id, user_id, etc.)
     * which needs the same field mapping to the frontend `Watchlist` type.
     */
    async createWatchlist(name: string): Promise<Watchlist> {
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>("/v1/watchlists", {
        method: "POST",
        body: { name },
        token: t,
      });

      return mapRawWatchlist(raw);
    },

    /**
     * renameWatchlist — rename a watchlist via PATCH /v1/watchlists/{id}
     *
     * WHY transform: S1 PATCH returns `WatchlistResponse` (id, user_id, …) which needs
     * the same field mapping to the frontend `Watchlist` type as create/get endpoints.
     */
    async renameWatchlist(watchlistId: string, newName: string): Promise<Watchlist> {
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>(`/v1/watchlists/${encodeURIComponent(watchlistId)}`, {
        method: "PATCH",
        body: { name: newName },
        token: t,
      });

      return mapRawWatchlist(raw);
    },

    /**
     * deleteWatchlist — delete a watchlist
     */
    deleteWatchlist(watchlistId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * addWatchlistMember — add an entity to a watchlist
     *
     * WHY transform: S1 returns `WatchlistMemberResponse` (the new member, not the full
     * watchlist). But the frontend expects the full `Watchlist` back. Since we don't have
     * the full watchlist data from S1's add-member response, we re-fetch the watchlist
     * after adding the member. This ensures the returned Watchlist has the correct member_count.
     */
    async addWatchlistMember(
      watchlistId: string,
      entityId: string,
    ): Promise<Watchlist> {
      // S1 returns the new WatchlistMemberResponse, not the full watchlist
      await apiFetch<{
        id: string;
        watchlist_id: string;
        entity_id: string;
        entity_type: string;
        added_at: string;
      }>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/members`,
        { method: "POST", body: { entity_id: entityId }, token: t },
      );

      // Re-fetch the watchlist to return the complete Watchlist object
      // WHY re-fetch: S1's add-member endpoint returns only the new member, not the
      // full watchlist. The frontend needs the complete Watchlist with updated members.
      return this.getWatchlist(watchlistId);
    },

    /**
     * removeWatchlistMember — remove an entity from a watchlist
     */
    removeWatchlistMember(
      watchlistId: string,
      entityId: string,
    ): Promise<void> {
      return apiFetch<void>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/members/${encodeURIComponent(entityId)}`,
        { method: "DELETE", token: t },
      );
    },

    // ── Alerts ────────────────────────────────────────────────────────

    /**
     * getPendingAlerts — paginated list of unacknowledged alerts
     */
    getPendingAlerts(params: PaginationParams = {}): Promise<AlertsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<AlertsResponse>(
        `/v1/alerts/pending${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },

    /**
     * acknowledgeAlert — dismiss an alert
     */
    acknowledgeAlert(alertId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/alerts/${encodeURIComponent(alertId)}/ack`,
        { method: "DELETE", token: t },
      );
    },

    // ── Chat ──────────────────────────────────────────────────────────

    /**
     * getThreads — user's conversation thread list
     */
    getThreads(): Promise<Thread[]> {
      return apiFetch<Thread[]>("/v1/threads", { token: t });
    },

    /**
     * createThread — start a new conversation thread
     */
    createThread(title?: string): Promise<Thread> {
      return apiFetch<Thread>("/v1/threads", {
        method: "POST",
        body: { title },
        token: t,
      });
    },

    /**
     * getThread — get thread with its full message history
     */
    getThread(threadId: string): Promise<Thread> {
      return apiFetch<Thread>(
        `/v1/threads/${encodeURIComponent(threadId)}`,
        { token: t },
      );
    },

    /**
     * deleteThread — delete a conversation thread
     */
    deleteThread(threadId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/threads/${encodeURIComponent(threadId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * streamChat — POST SSE streaming chat response
     *
     * WHY fetch() not EventSource: EventSource is GET-only and can't send
     * a request body with the question. We use fetch() + ReadableStream for
     * POST-based SSE. The token goes in the Authorization header (not URL).
     * See PRD-0028 §6.2 Chat Routes for streaming protocol details.
     *
     * Returns a native ReadableStream — the ChatUI component reads chunks
     * via response.body.getReader().
     */
    async streamChat(request: ChatStreamRequest): Promise<ReadableStream<Uint8Array> | null> {
      const response = await fetch(`${BASE}/v1/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(t ? { Authorization: `Bearer ${t}` } : {}),
        },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        throw new GatewayError(response.status, response.statusText);
      }

      // Return the raw ReadableStream — ChatUI reads it with getReader()
      return response.body;
    },

    // ── Prediction Markets ────────────────────────────────────────────

    /**
     * getPredictionMarkets — open/live prediction market odds
     *
     * WHY transform: S3 returns `PredictionMarketsListResponse` = `{items: [...], total, limit, offset}`
     * where each item is a `PredictionMarketSummaryResponse` with fields like `question` (not `title`),
     * `outcomes` array (not `yes_probability`/`no_probability`), `resolution_status` (not `status`),
     * and `volume_24h` (not `volume_usd`). The frontend expects `PredictionMarketsResponse` =
     * `{markets: PredictionMarket[], total}` with the simpler yes/no probability model.
     */
    async getPredictionMarkets(
      params: { status?: string; limit?: number } = {},
    ): Promise<PredictionMarketsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();

      // S3 returns PredictionMarketsListResponse with `items` (not `markets`)
      const raw = await apiFetch<{
        items: Array<{
          market_id: string;
          question: string;
          outcomes: Array<{ name: string; token_id: string; price: number }>;
          volume_24h: number | null;
          close_time: string | null;
          resolution_status: string;
          resolved_answer: string | null;
          updated_at: string;
          // WHY market_slug: added in B-2 (migration 009); may be null for markets
          // ingested before the field was added. Null → empty URL → search fallback.
          market_slug: string | null;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(
        `/v1/signals/prediction-markets${qs ? `?${qs}` : ""}`,
        { token: t },
      );

      // Transform S3 summary responses into frontend PredictionMarket type
      const markets: PredictionMarket[] = (raw.items ?? []).map((m) => {
        // WHY outcome extraction: S3 stores outcomes as an array of {name, token_id, price}
        // where price is the implied probability (0.0–1.0). The frontend expects simple
        // yes_probability/no_probability fields. We look for "Yes"/"No" outcomes by name.
        const yesOutcome = m.outcomes.find((o) => o.name.toLowerCase() === "yes");
        const noOutcome = m.outcomes.find((o) => o.name.toLowerCase() === "no");

        return {
          market_id: m.market_id,
          title: m.question, // S3 calls it "question", frontend calls it "title"
          description: "", // Summary response doesn't include description (detail endpoint does)
          yes_probability: yesOutcome?.price ?? 0,
          no_probability: noOutcome?.price ?? (1 - (yesOutcome?.price ?? 0.5)),
          volume_usd: m.volume_24h ?? 0, // S3 uses volume_24h, frontend uses volume_usd
          // WHY map resolution_status → status: S3 uses "open"/"resolved"/"cancelled",
          // frontend expects "open"/"closed"/"resolved". Map "cancelled" → "closed".
          status: (m.resolution_status === "cancelled" ? "closed" : m.resolution_status) as
            "open" | "closed" | "resolved",
          resolution_date: m.close_time,
          entity_ids: [], // Not available in summary response — would need entity linking
          tickers: [], // Same — summary doesn't include ticker associations
          source: "polymarket" as const, // Currently only Polymarket is integrated (PRD-0019)
          // WHY construct URL from market_slug: S3 now returns the Polymarket event slug
          // (migration 009). Null slug → empty URL → PredictionMarketsWidget falls back
          // to a search URL so clicking a row always opens a real page (Wave A-4).
          url: m.market_slug ? `https://polymarket.com/event/${m.market_slug}` : "",
          // WHY pass market_slug through: PredictionMarketsWidget (Wave A-4) builds
          // the URL client-side using market_slug as a second fallback after url.
          // Preserving it avoids re-fetching when url is empty.
          market_slug: m.market_slug,
          updated_at: m.updated_at,
        };
      });

      return { markets, total: raw.total };
    },

    /**
     * getPredictionMarketHistory — time-series of yes-probability snapshots
     *
     * WHY THIS EXISTS (PLAN-0048 D-2): the dashboard PredictionMarketsWidget
     * needs (a) a 24h Δ pp computed from the most recent two snapshots and
     * (b) a 7-day mini sparkline. Both come from the existing S9 → S3 history
     * proxy at `/v1/signals/prediction-markets/{id}/history`.
     *
     * WHY days-only API surface: callers use day windows (1d for delta,
     * 7d for sparkline). We translate `days` to a `from=now-Nd` query param
     * so the caller doesn't have to format ISO dates.
     *
     * WHY shaped: the S3 response uses `outcomes_prices: { Yes, No }` per
     * snapshot. We extract `yes_probability` for the dashboard widget so
     * the consumer doesn't need to re-implement the same lookup logic.
     */
    async getPredictionMarketHistory(
      marketId: string,
      days = 7,
    ): Promise<{ market_id: string; points: Array<{ snapshot_at: string; yes_probability: number }> }> {
      // Compute the `from` timestamp client-side. WHY ISO + Z: FastAPI's
      // `datetime` query param expects ISO 8601; the trailing Z keeps it UTC.
      const fromIso = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
      const qs = new URLSearchParams({ from: fromIso, limit: "200" }).toString();

      const raw = await apiFetch<{
        market_id: string;
        snapshots: Array<{
          snapshot_at: string;
          outcomes_prices: Record<string, number>;
          volume_24h: number | null;
        }>;
      }>(
        `/v1/signals/prediction-markets/${encodeURIComponent(marketId)}/history?${qs}`,
        { token: t },
      );

      // Map each snapshot to a simple {snapshot_at, yes_probability} pair.
      // WHY default 0: if the outcome key is missing (rare — early ingestion
      // gap), 0 is safer than NaN for sparkline rendering. The chart still
      // looks reasonable; the trader sees the gap.
      const points = (raw.snapshots ?? []).map((s) => ({
        snapshot_at: s.snapshot_at,
        yes_probability: s.outcomes_prices?.Yes ?? s.outcomes_prices?.yes ?? 0,
      }));

      // S3 returns snapshots ORDER BY snapshot_at DESC. The sparkline + delta
      // logic below expects ascending (oldest → newest) order so the path
      // moves left-to-right in time. Reverse here once instead of in every
      // consumer.
      points.reverse();

      return { market_id: raw.market_id, points };
    },

    // ── Dashboard composed endpoints ──────────────────────────────────

    /**
     * getMarketHeatmap — GICS sector performance for dashboard
     *
     * WHY period param: PLAN-0043 B-4 wires the period selector buttons (1D/1W/1M)
     * in the dashboard SectorHeatmapWidget to the S9 endpoint. Passing period here
     * ensures TanStack Query re-fetches when the user switches periods.
     * - 1D: S9 makes 11 parallel screener calls (one per GICS sector)
     * - 1W/1M: S9 delegates to S3 OHLCV aggregate endpoint (more accurate)
     */
    getMarketHeatmap(period: "1D" | "1W" | "1M" = "1D"): Promise<MarketHeatmapResponse> {
      return apiFetch<MarketHeatmapResponse>(
        `/v1/market/heatmap?period=${period}`,
        { token: t },
      );
    },

    /**
     * getTopMovers — top gainers or losers by daily return
     *
     * WHY transform: S9's get_top_movers() composed endpoint returns the raw S3 screener
     * response `{results: [{instrument_id, symbol, exchange, metrics: {daily_return, ...}}], total, ...}`
     * — NOT the `{movers: Mover[], type}` shape the frontend expects. Each screener result
     * uses `symbol` (not `ticker`), nests daily_return inside a `metrics` object, and has
     * no `price` or `name` field. We extract what we can and default the rest.
     */
    async getTopMovers(
      moverType: "gainers" | "losers" = "gainers",
      limit = 10,
      // WHY period param: PLAN-0043 B-4 wires the period selector buttons (1D/1W/1M)
      // in PreMarketMoversWidget to the S9 endpoint. The period is passed through to
      // S9 which routes 1D → screener and 1W/1M → S3 OHLCV period-movers endpoint.
      // Default 1D keeps backward compatibility.
      period: "1D" | "1W" | "1M" = "1D",
    ): Promise<TopMoversResponse> {
      // S9 composed endpoint returns raw screener results from S3.
      // S3's ScreenInstrumentResponse uses field name `ticker` (not `symbol`).
      // We include both in the type so the transform handles either shape.
      const raw = await apiFetch<{
        results?: Array<{
          instrument_id?: string;
          // WHY entity_id optional here: S3 screener results do not always include entity_id.
          // When present (e.g. after S7 entity-linking enrichment) we preserve it so downstream
          // navigation can use the stable ADR-F-12 entity_id rather than instrument_id.
          entity_id?: string;
          ticker?: string;   // S3 ScreenInstrumentResponse field name
          symbol?: string;   // legacy / alternate field name kept for forward compat
          name?: string;
          exchange?: string;
          metrics?: {
            daily_return?: number;
            market_cap?: number;
            [key: string]: unknown;
          };
          [key: string]: unknown;
        }>;
        // S9 may also return the shaped response if it's been fixed server-side
        movers?: Array<{
          instrument_id: string;
          entity_id?: string | null; // present when S9 enriches top-movers with knowledge graph IDs
          ticker: string;
          name: string;
          price: number;
          change_pct: number;
          volume: number | null;
        }>;
        type?: string;
        total?: number;
      }>(
        `/v1/market/top-movers?type=${moverType}&limit=${limit}&period=${period}`,
        { token: t },
      );

      // WHY check both shapes: S9 may be updated in the future to return the correct shape.
      // If `movers` is already present, use it directly. Otherwise, transform from screener results.
      if (raw.movers) {
        return { movers: raw.movers, type: (raw.type as "gainers" | "losers") ?? moverType };
      }

      // Transform screener results into Mover[] format.
      // WHY ticker ?? symbol fallback: S3's ScreenInstrumentResponse uses `ticker`.
      // Some older or alternate responses may use `symbol`. Try both so the widget
      // always shows a symbol string instead of an empty cell.
      // F-304 fix (PLAN-0048 QA iter-1): pull the latest close/price from
      // any of the metric fields S3 may surface so we never display $0.00
      // for a real ticker — and apply strict directional filtering below.
      const movers = (raw.results ?? []).map((r) => {
        const metrics = (r.metrics ?? {}) as Record<string, unknown>;
        // S3's screener returns price under various keys depending on the
        // configured metric set: `close`, `last_price`, or sometimes a flat
        // `price`. Probe all three before falling back to 0 — this rescues
        // the $0.00 rows the audit captured in /tmp/qa-iter1/d1920-top-movers.
        const priceFromMetrics =
          typeof metrics.close === "number"
            ? metrics.close
            : typeof metrics.last_price === "number"
              ? metrics.last_price
              : typeof metrics.price === "number"
                ? metrics.price
                : typeof (r as Record<string, unknown>).price === "number"
                  ? ((r as Record<string, unknown>).price as number)
                  : 0;
        return {
          instrument_id: r.instrument_id ?? "",
          // WHY propagate entity_id when present: top-mover rows need it for correct
          // instrument detail navigation. ADR-F-12 mandates entity_id in URLs.
          // Falls back to undefined so the UI can degrade to instrument_id-based routing.
          entity_id: r.entity_id ?? undefined,
          ticker: r.ticker ?? r.symbol ?? r.name?.split(" ")[0] ?? r.instrument_id?.slice(0, 6) ?? "",
          name: r.name ?? r.ticker ?? r.symbol ?? "", // name for tooltip/detail
          price: priceFromMetrics,
          // WHY * 100: S3 daily_return is a decimal fraction (0.031 = 3.1%).
          // The Mover.change_pct field is treated as a percentage by MoverRow
          // (mover.change_pct.toFixed(2) → "3.11"). Multiply to convert.
          change_pct: (r.metrics?.daily_return ?? 0) * 100,
          volume: null as number | null,
        };
      });

      // F-304 fix (PLAN-0048 QA iter-1): the audit observed the gainers
      // list contained negative-% rows (e.g. GOOGL -0.54%) and the same
      // ticker appeared in BOTH the gainers and losers panes. The screener
      // sometimes returns rows whose daily_return is opposite to the
      // requested side when the underlying sort is unstable — strict
      // directional filtering on the client guarantees gainers > 0 and
      // losers < 0 regardless of upstream behaviour.
      const filtered = movers.filter((m) =>
        moverType === "gainers" ? m.change_pct > 0 : m.change_pct < 0,
      );

      return { movers: filtered, type: moverType };
    },

    /**
     * getEconomicCalendar — upcoming macro economic events
     */
    getEconomicCalendar(): Promise<EconomicCalendarResponse> {
      return apiFetch<EconomicCalendarResponse>(
        "/v1/fundamentals/economic-calendar",
        { token: t },
      );
    },

    /**
     * getMorningBrief — AI-generated morning brief (24h Valkey cache)
     */
    getMorningBrief(): Promise<BriefingResponse> {
      return apiFetch<BriefingResponse>("/v1/briefings/morning", { token: t });
    },

    /**
     * getInstrumentBrief — per-instrument AI brief
     */
    getInstrumentBrief(entityId: string): Promise<BriefingResponse> {
      return apiFetch<BriefingResponse>(
        `/v1/briefings/instrument/${encodeURIComponent(entityId)}`,
        { token: t },
      );
    },

    /**
     * getAiSignals — S6 price-impact signal scores (PRD-0020)
     */
    getAiSignals(limit = 8): Promise<AiSignalsResponse> {
      return apiFetch<AiSignalsResponse>(`/v1/signals/ai?limit=${limit}`, {
        token: t,
      });
    },

    // ── Brokerage ─────────────────────────────────────────────────────

    /**
     * getBrokerageConnections — list SnapTrade connections for the user
     *
     * WHY optional portfolioId: the UI can either show all connections (settings page)
     * or filter to a specific portfolio (portfolio brokerages tab). Both use cases
     * share this single method with an optional filter parameter.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections?portfolio_id=...
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    async getBrokerageConnections(portfolioId?: string): Promise<BrokerageConnection[]> {
      // Build query string only when portfolioId is provided
      const qs = portfolioId
        ? `?portfolio_id=${encodeURIComponent(portfolioId)}`
        : "";

      const raw = await apiFetch<{ items: BrokerageConnection[] }>(
        `/v1/brokerage-connections${qs}`,
        { token: t },
      );

      // WHY ?? []: guard against S9 returning null items on empty result set
      return raw.items ?? [];
    },

    /**
     * initiateBrokerageConnection — create a pending connection and get redirect URI
     *
     * WHY snaptrade_tos_accepted: SnapTrade requires the end-user's explicit ToS
     * acceptance to be recorded with each connection initiation. The frontend
     * shows a checkbox in ConnectBrokerageModal that the user must tick before
     * this method is called — we forward their acceptance to S9/S1.
     *
     * On success: immediately redirect window.location.href to redirect_uri
     * (SnapTrade portal — user selects their broker and authorises access).
     *
     * DATA SOURCE: S9 POST /api/v1/brokerage-connections
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    initiateBrokerageConnection(
      portfolioId: string,
    ): Promise<InitiateBrokerageConnectionResponse> {
      return apiFetch<InitiateBrokerageConnectionResponse>(
        "/v1/brokerage-connections",
        {
          method: "POST",
          // WHY snaptrade_tos_accepted: true: the ConnectBrokerageModal checkbox
          // gate ensures the user has accepted ToS before triggering this mutation.
          body: { portfolio_id: portfolioId, snaptrade_tos_accepted: true },
          token: t,
        },
      );
    },

    /**
     * disconnectBrokerageConnection — revoke access and remove connection
     *
     * WHY void return: DELETE 204 has no response body. The component invalidates
     * the connection list query to reflect the removal in the UI.
     *
     * DATA SOURCE: S9 DELETE /api/v1/brokerage-connections/{id}
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    disconnectBrokerageConnection(connectionId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * triggerBrokerageSync — ask S1 to immediately re-sync this connection
     *
     * WHY 202 Accepted (not 200 OK): the sync is asynchronous — the worker picks
     * it up from a task queue. The response immediately confirms queuing, not
     * completion. The component should refetch connection list after a short delay
     * to see the updated last_synced_at and status.
     *
     * DATA SOURCE: S9 POST /api/v1/brokerage-connections/{id}/sync
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    triggerBrokerageSync(
      connectionId: string,
    ): Promise<{ status: string; connection_id: string }> {
      return apiFetch<{ status: string; connection_id: string }>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/sync`,
        { method: "POST", token: t },
      );
    },

    /**
     * getSyncErrors — list transaction-level sync errors for a connection
     *
     * WHY these are non-fatal: sync errors are per-transaction (unknown instrument,
     * unsupported type, etc.). Other transactions in the same sync succeeded.
     * The UI shows them as warnings in SyncErrorsBanner, not as connection failures.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/sync-errors?limit=N
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    async getSyncErrors(connectionId: string, limit = 50): Promise<SyncError[]> {
      const raw = await apiFetch<{ items: SyncError[] }>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/sync-errors?limit=${limit}`,
        { token: t },
      );

      // WHY ?? []: guard against null items field on empty error list
      return raw.items ?? [];
    },

    /**
     * activateBrokerageConnection — complete the OAuth callback flow
     *
     * WHY this is a GET (not POST): SnapTrade redirects the user's browser to
     * our callback page with params in the URL query string. We call S9's GET
     * endpoint with those params to activate the connection server-side.
     *
     * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/callback
     * DESIGN REFERENCE: PRD-0022 §6.6
     */
    activateBrokerageConnection(
      connectionId: string,
      params: { authorizationId: string; userId: string; sessionId: string },
    ): Promise<BrokerageConnection> {
      const qs = new URLSearchParams({
        authorizationId: params.authorizationId,
        userId: params.userId,
        sessionId: params.sessionId,
      }).toString();

      return apiFetch<BrokerageConnection>(
        `/v1/brokerage-connections/${encodeURIComponent(connectionId)}/callback?${qs}`,
        { token: t },
      );
    },

    // ── Search ────────────────────────────────────────────────────────

    /**
     * searchInstruments — global instrument search for TopBar command palette
     * Public endpoint — no token needed
     *
     * WHY transform: S9 proxies to S3's `GET /api/v1/instruments` which returns
     * `InstrumentListResponse` = `{items: [{id, security_id, symbol, exchange, is_active, flags, created_at}], total, limit, offset}`.
     * The frontend expects `SearchResponse` = `{results: SearchResult[], query: string}` where each
     * result has `instrument_id`, `entity_id`, `ticker` (not `symbol`), `name`, and `type`.
     * S3 instruments have no `name` field or `entity_id` — we synthesise from available data.
     */
    async searchInstruments(q: string, limit = 10): Promise<SearchResponse> {
      // S3 returns InstrumentListResponse with `items` array
      const raw = await apiFetch<{
        items: Array<{
          id: string;
          security_id: string;
          symbol: string;
          exchange: string;
          is_active: boolean;
          flags: {
            has_ohlcv: boolean;
            has_quotes: boolean;
            has_fundamentals: boolean;
          };
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(
        `/v1/search/instruments?q=${encodeURIComponent(q)}&limit=${limit}`,
      );

      // Transform S3 InstrumentResponse into frontend SearchResult type
      const results: SearchResult[] = (raw.items ?? []).map((inst) => ({
        instrument_id: inst.id,
        // WHY same as instrument_id: S3 does not track entity_id on instruments.
        // Entity linking happens in S7 Knowledge Graph. Using instrument_id as fallback
        // so navigation works (Instrument Detail page accepts either ID).
        entity_id: inst.id,
        ticker: inst.symbol, // S3 calls it "symbol", frontend calls it "ticker"
        // WHY synthesised name: S3's InstrumentResponse has no `name` field.
        // We create a readable name from "SYMBOL (EXCHANGE)" for display in the
        // search results dropdown. The real name comes from fundamentals data.
        name: `${inst.symbol} (${inst.exchange})`,
        exchange: inst.exchange,
        // WHY derive type from flags: S3 doesn't have an explicit instrument type field.
        // We infer "equity" as default since most instruments in the system are equities.
        // A more accurate mapping would require fundamentals data (asset_class field).
        type: "equity",
      }));

      return { results, query: q };
    },

    /**
     * searchFundamentals — entity-aware instrument search.
     *
     * WHY this exists (BUG-7 / B-3): `searchInstruments` queries S3 which has no
     * concept of `entity_id` — it falls back to `entity_id = instrument_id`. The
     * watchlist add-member endpoint requires the REAL KG entity_id from S7. Posting
     * an instrument_id silently fails or produces an orphaned member.
     *
     * Live-stack reality (verified 2026-04-28): the fundamentals screener does NOT
     * support text search (only numeric metric filters), and S3's
     * /v1/search/instruments returns no entity_id. The reliable path is:
     *  1) S3 search to find candidate instrument_ids matching the query,
     *  2) /v1/companies/{id}/overview per candidate to get the real entity_id +
     *     authoritative ticker/name from the KG-joined view.
     *
     * WHY parallelised overviews: the search returns at most `limit` candidates
     * (usually ≤8). Promise.all on a handful of GETs is cheaper than sequential.
     * WHY catch+filter: a missing overview shouldn't abort the entire dropdown —
     * we just drop that row and surface the rest.
     */
    async searchFundamentals(q: string, limit = 8): Promise<SearchResponse> {
      const trimmed = q.trim();
      if (!trimmed) return { results: [], query: q };
      // Step 1: candidate instruments from S3 search
      const candidates = await this.searchInstruments(trimmed, limit);
      if (candidates.results.length === 0) return { results: [], query: q };
      // Step 2: enrich each candidate with the real entity_id via the overview endpoint
      const enriched = await Promise.all(
        candidates.results.map(async (cand) => {
          try {
            const ov = await this.getCompanyOverview(cand.instrument_id);
            // WHY guard against missing entity_id: stale or unsynced instruments
            // may have null entity_id — those cannot be added to a watchlist.
            if (!ov.instrument?.entity_id) return null;
            return {
              instrument_id: cand.instrument_id,
              entity_id: ov.instrument.entity_id,
              ticker: ov.instrument.ticker ?? cand.ticker,
              name: ov.instrument.name ?? cand.name,
              exchange: ov.instrument.exchange ?? cand.exchange ?? "—",
              type: cand.type,
            } satisfies SearchResult;
          } catch {
            return null;
          }
        }),
      );
      const results = enriched.filter((r): r is SearchResult => r !== null);
      return { results, query: q };
    },
  };
}

/**
 * Type of the gateway object (for mocking in tests)
 * Usage: const mockGateway: Gateway = { ... }
 */
export type Gateway = ReturnType<typeof createGateway>;
