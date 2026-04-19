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
 * - `members` defaults to [] (S1 list endpoint does not include members)
 * - `updated_at` defaults to `created_at` (S1 does not track updated_at on watchlists)
 */
function mapRawWatchlist(raw: {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  status: string;
  created_at: string;
}): Watchlist {
  return {
    watchlist_id: raw.id,
    name: raw.name,
    owner_id: raw.user_id,
    members: [] as WatchlistMember[],
    member_count: 0,
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
      // S1 returns a plain array of HoldingResponse objects
      const raw = await apiFetch<
        Array<{
          id: string;
          portfolio_id: string;
          instrument_id: string;
          quantity: string; // S1 serialises Decimal as "0.00000000" string
          average_cost: string; // same decimal string format
          currency: string;
        }>
      >(`/v1/holdings/${encodeURIComponent(portfolioId)}`, { token: t });

      // Normalise: if S1 somehow returns null (shouldn't happen), treat as empty array
      const items = Array.isArray(raw) ? raw : [];

      // Transform S1 HoldingResponse into frontend Holding type
      const holdings: Holding[] = items.map((h) => ({
        holding_id: h.id,
        portfolio_id: h.portfolio_id,
        instrument_id: h.instrument_id,
        // WHY empty string defaults: S1 does not return entity_id, ticker, or name on holdings.
        // These are enriched later by the PortfolioPage component via batch quote lookups.
        // Using empty defaults prevents TypeScript errors and allows graceful degradation.
        entity_id: "",
        ticker: "",
        name: "",
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
          currency: string;
          executed_at: string;
          external_ref: string | null;
          created_at: string;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(`/v1/transactions?${qs}`, { token: t });

      // Transform S1 TransactionListItem into frontend Transaction type
      const transactions: Transaction[] = (raw.items ?? []).map((tx) => ({
        transaction_id: tx.id,
        portfolio_id: tx.portfolio_id,
        instrument_id: tx.instrument_id,
        // WHY empty ticker: S1 does not include ticker on TransactionListItem.
        // The component can look it up from the instrument cache if needed.
        ticker: "",
        // WHY map direction to type: S1 uses separate transaction_type (TRADE, DIVIDEND, etc.)
        // and direction (BUY, SELL) fields. The frontend simplifies this to a single "BUY" | "SELL" type.
        // We use the direction field which maps directly to the frontend's BUY/SELL enum.
        type: tx.direction.toUpperCase() as "BUY" | "SELL",
        quantity: parseFloat(tx.quantity) || 0,
        price: parseFloat(tx.price) || 0,
        fee: parseFloat(tx.fees) || 0,
        currency: tx.currency,
        executed_at: tx.executed_at,
        notes: tx.external_ref,
      }));

      return {
        transactions,
        total: raw.total,
        offset: raw.offset,
        limit: raw.limit,
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
     * WHY transform: Same field mapping as getWatchlists() — S1 returns `WatchlistResponse`
     * with `id`/`user_id`. Note: S1 does NOT include members in the single-watchlist response
     * either (the route returns WatchlistResponse, not a joined response). Members would need
     * a separate GET /watchlists/{id}/members call if S1 exposed one. For now, members default
     * to an empty array and the component handles the empty state.
     */
    async getWatchlist(watchlistId: string): Promise<Watchlist> {
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

      return mapRawWatchlist(raw);
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
          url: "", // Not available in summary response
          updated_at: m.updated_at,
        };
      });

      return { markets, total: raw.total };
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
    ): Promise<TopMoversResponse> {
      // S9 composed endpoint returns raw screener results from S3
      const raw = await apiFetch<{
        results?: Array<{
          instrument_id?: string;
          symbol?: string;
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
          ticker: string;
          name: string;
          price: number;
          change_pct: number;
          volume: number | null;
        }>;
        type?: string;
        total?: number;
      }>(
        `/v1/market/top-movers?type=${moverType}&limit=${limit}`,
        { token: t },
      );

      // WHY check both shapes: S9 may be updated in the future to return the correct shape.
      // If `movers` is already present, use it directly. Otherwise, transform from screener results.
      if (raw.movers) {
        return { movers: raw.movers, type: (raw.type as "gainers" | "losers") ?? moverType };
      }

      // Transform screener results into Mover[] format
      const movers = (raw.results ?? []).map((r) => ({
        instrument_id: r.instrument_id ?? "",
        ticker: r.symbol ?? "",
        name: r.name ?? r.symbol ?? "", // Fall back to symbol if name not available
        price: 0, // Not available from screener — would need a quote lookup
        change_pct: r.metrics?.daily_return ?? 0,
        volume: null as number | null,
      }));

      return { movers, type: moverType };
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
  };
}

/**
 * Type of the gateway object (for mocking in tests)
 * Usage: const mockGateway: Gateway = { ... }
 */
export type Gateway = ReturnType<typeof createGateway>;
