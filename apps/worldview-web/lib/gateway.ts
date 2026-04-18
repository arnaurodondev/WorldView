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
  EntityGraph,
  ContradictionsResponse,
  NewsResponse,
  ScreenerField,
  ScreenerRequest,
  ScreenerResponse,
  Portfolio,
  HoldingsResponse,
  TransactionsResponse,
  TransactionRequest,
  Transaction,
  Watchlist,
  AlertsResponse,
  Thread,
  ChatStreamRequest,
  PredictionMarketsResponse,
  EconomicCalendarResponse,
  MarketHeatmapResponse,
  TopMoversResponse,
  SearchResponse,
  AiSignalsResponse,
  MorningBrief,
  PaginationParams,
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
     * timeframe: "1D" | "1H" | "5M"
     */
    getOHLCV(
      instrumentId: string,
      params: { timeframe?: string; start?: string; end?: string } = {},
    ): Promise<OHLCVResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null) as [string, string][],
      ).toString();
      return apiFetch<OHLCVResponse>(
        `/v1/ohlcv/${encodeURIComponent(instrumentId)}${qs ? `?${qs}` : ""}`,
        { token: t },
      );
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
     * Body: { ids: string[] }
     */
    getBatchQuotes(ids: string[]): Promise<BatchQuoteResponse> {
      return apiFetch<BatchQuoteResponse>("/v1/quotes/batch", {
        method: "POST",
        body: { ids },
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

    // ── Knowledge Graph ───────────────────────────────────────────────

    /**
     * getEntityGraph — egocentric knowledge graph for sigma.js
     * depth: number of hops from center node (default 2)
     */
    getEntityGraph(
      entityId: string,
      depth = 2,
    ): Promise<EntityGraph> {
      return apiFetch<EntityGraph>(
        `/v1/entities/${encodeURIComponent(entityId)}/graph?depth=${depth}`,
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
     * getTopNews — ranked news feed by relevance/impact score (PRD-0026)
     * Used by: Dashboard WatchlistNews, Alerts/News page → Top Today tab
     */
    getTopNews(params: { hours?: number; limit?: number; offset?: number } = {}): Promise<NewsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<NewsResponse>(`/v1/news/top${qs ? `?${qs}` : ""}`);
      // WHY no auth: news/top is a public endpoint (see proxy.py T-S9-1-03)
    },

    /**
     * getEntityNews — scored news articles for a specific entity
     * Used by Instrument Detail → News tab
     */
    getEntityNews(
      entityId: string,
      params: {
        start_date?: string;
        end_date?: string;
        order_by?: string;
        limit?: number;
        offset?: number;
      } = {},
    ): Promise<NewsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<NewsResponse>(
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
     */
    getPortfolios(): Promise<Portfolio[]> {
      return apiFetch<Portfolio[]>("/v1/portfolios", { token: t });
    },

    /**
     * getHoldings — holdings + P&L summary for a portfolio
     */
    getHoldings(portfolioId: string): Promise<HoldingsResponse> {
      return apiFetch<HoldingsResponse>(
        `/v1/holdings/${encodeURIComponent(portfolioId)}`,
        { token: t },
      );
    },

    /**
     * getTransactions — paginated transaction history
     */
    getTransactions(
      portfolioId: string,
      params: PaginationParams = {},
    ): Promise<TransactionsResponse> {
      const qs = new URLSearchParams({
        portfolio_id: portfolioId,
        ...(params.limit != null ? { limit: String(params.limit) } : {}),
        ...(params.offset != null ? { offset: String(params.offset) } : {}),
      }).toString();
      return apiFetch<TransactionsResponse>(`/v1/transactions?${qs}`, {
        token: t,
      });
    },

    /**
     * addTransaction — record a buy or sell
     */
    addTransaction(tx: TransactionRequest): Promise<Transaction> {
      return apiFetch<Transaction>("/v1/transactions", {
        method: "POST",
        body: tx,
        token: t,
      });
    },

    // ── Watchlists ────────────────────────────────────────────────────

    /**
     * getWatchlists — list all watchlists for the authenticated user
     */
    getWatchlists(): Promise<Watchlist[]> {
      return apiFetch<Watchlist[]>("/v1/watchlists", { token: t });
    },

    /**
     * getWatchlist — single watchlist with member list
     */
    getWatchlist(watchlistId: string): Promise<Watchlist> {
      return apiFetch<Watchlist>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}`,
        { token: t },
      );
    },

    /**
     * createWatchlist — create a new watchlist
     */
    createWatchlist(name: string): Promise<Watchlist> {
      return apiFetch<Watchlist>("/v1/watchlists", {
        method: "POST",
        body: { name },
        token: t,
      });
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
     */
    addWatchlistMember(
      watchlistId: string,
      entityId: string,
    ): Promise<Watchlist> {
      return apiFetch<Watchlist>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/members`,
        { method: "POST", body: { entity_id: entityId }, token: t },
      );
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
     */
    getPredictionMarkets(
      params: { status?: string; limit?: number } = {},
    ): Promise<PredictionMarketsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<PredictionMarketsResponse>(
        `/v1/signals/prediction-markets${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },

    // ── Dashboard composed endpoints ──────────────────────────────────

    /**
     * getMarketHeatmap — GICS sector performance for dashboard
     */
    getMarketHeatmap(): Promise<MarketHeatmapResponse> {
      return apiFetch<MarketHeatmapResponse>("/v1/market/heatmap", {
        token: t,
      });
    },

    /**
     * getTopMovers — top gainers or losers by daily return
     */
    getTopMovers(
      type: "gainers" | "losers" = "gainers",
      limit = 10,
    ): Promise<TopMoversResponse> {
      return apiFetch<TopMoversResponse>(
        `/v1/market/top-movers?type=${type}&limit=${limit}`,
        { token: t },
      );
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
    getMorningBrief(): Promise<MorningBrief> {
      return apiFetch<MorningBrief>("/v1/briefings/morning", { token: t });
    },

    /**
     * getInstrumentBrief — per-instrument AI brief
     */
    getInstrumentBrief(entityId: string): Promise<MorningBrief> {
      return apiFetch<MorningBrief>(
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

    // ── Search ────────────────────────────────────────────────────────

    /**
     * searchInstruments — global instrument search for TopBar command palette
     * Public endpoint — no token needed
     */
    searchInstruments(q: string, limit = 10): Promise<SearchResponse> {
      return apiFetch<SearchResponse>(
        `/v1/search/instruments?q=${encodeURIComponent(q)}&limit=${limit}`,
      );
    },
  };
}

/**
 * Type of the gateway object (for mocking in tests)
 * Usage: const mockGateway: Gateway = { ... }
 */
export type Gateway = ReturnType<typeof createGateway>;
