/**
 * __tests__/gateway.test.ts — Unit tests for lib/gateway.ts
 *
 * WHY THESE TESTS EXIST: The gateway client is the critical path for all data
 * access. Tests verify:
 * 1. Correct URL construction (wrong paths = silent data failure)
 * 2. Auth header injection (missing token = 401 errors in production)
 * 3. POST body serialisation (wrong body = S9 validation errors)
 * 4. GatewayError thrown on non-2xx (uncaught errors = blank panels)
 *
 * Strategy: Mock global fetch() — we test the gateway's URL/header logic,
 * not the HTTP stack itself. Integration tests against a running S9 are
 * separate (see e2e/ directory in T-1 wave).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createGateway, GatewayError } from "@/lib/gateway";

// ── Test helpers ──────────────────────────────────────────────────────────

function mockFetch(status: number, body: unknown = {}) {
  // Replace global fetch with a mock that returns the given status/body
  const mockResponse = {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    body: null,
  };
  return vi.spyOn(global, "fetch").mockResolvedValue(
    mockResponse as unknown as Response,
  );
}

beforeEach(() => {
  // Reset all mocks between tests to prevent state leakage
  vi.restoreAllMocks();
});

// ── URL construction ─────────────────────────────────────────────────────

describe("createGateway() — URL construction", () => {
  it("calls /api/v1/portfolios for getPortfolios()", async () => {
    // WHY {items: []}: S1 returns PaginatedResponse<PortfolioResponse> envelope.
    // The gateway unwraps .items and maps id → portfolio_id.
    const spy = mockFetch(200, { items: [], total: 0, limit: 100, offset: 0 });
    const gw = createGateway("test-token");
    await gw.getPortfolios();

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/portfolios");
  });

  it("constructs correct holdings URL with portfolio ID", async () => {
    // WHY bare array: S1 returns list[HoldingResponse] (not wrapped in an object).
    // The gateway wraps it into HoldingsResponse = {portfolio_id, holdings: [...], ...}
    const spy = mockFetch(200, []);
    const gw = createGateway("test-token");
    await gw.getHoldings("portfolio-123");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/holdings/portfolio-123");
  });

  it("URL-encodes instrument IDs with special chars", async () => {
    const spy = mockFetch(200, { bars: [] });
    const gw = createGateway("test-token");
    await gw.getOHLCV("ETF/US:SPY");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain(encodeURIComponent("ETF/US:SPY"));
  });

  it("constructs batch quotes URL correctly", async () => {
    const spy = mockFetch(200, { quotes: {} });
    const gw = createGateway("test-token");
    await gw.getBatchQuotes(["id-1", "id-2"]);

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/quotes/batch");
  });

  it("constructs search URL with query params", async () => {
    // WHY {items: []}: S3 returns InstrumentListResponse, gateway transforms to SearchResponse
    const spy = mockFetch(200, { items: [], total: 0, limit: 5, offset: 0 });
    const gw = createGateway();
    await gw.searchInstruments("apple", 5);

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("apple");
    expect(calledUrl).toContain("limit=5");
  });

  it("top movers includes type and limit params", async () => {
    const spy = mockFetch(200, { movers: [], type: "gainers" });
    const gw = createGateway("test-token");
    await gw.getTopMovers("gainers", 10);

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("type=gainers");
    expect(calledUrl).toContain("limit=10");
  });
});

// ── Auth header injection ─────────────────────────────────────────────────

describe("createGateway() — auth headers", () => {
  it("injects Authorization header when token provided", async () => {
    // WHY {items: []}: S1 returns paginated envelope, gateway expects this shape
    const spy = mockFetch(200, { items: [], total: 0, limit: 100, offset: 0 });
    const gw = createGateway("my-bearer-token");
    await gw.getPortfolios();

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer my-bearer-token");
  });

  it("does not inject Authorization when no token", async () => {
    // WHY {items: []}: S3 InstrumentListResponse shape, gateway transforms to SearchResponse
    const spy = mockFetch(200, { items: [], total: 0, limit: 10, offset: 0 });
    const gw = createGateway(); // no token
    await gw.searchInstruments("apple");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBeUndefined();
  });

  it("does not inject Authorization when null token", async () => {
    const spy = mockFetch(200, { items: [], total: 0, limit: 10, offset: 0 });
    const gw = createGateway(null);
    await gw.searchInstruments("test");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBeUndefined();
  });
});

// ── POST body serialisation ───────────────────────────────────────────────

describe("createGateway() — POST body", () => {
  it("serialises batch quote IDs as JSON array", async () => {
    const spy = mockFetch(200, { quotes: {} });
    const gw = createGateway("token");
    await gw.getBatchQuotes(["id-1", "id-2", "id-3"]);

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    expect(calledInit?.method).toBe("POST");
    // WHY instrument_ids (not ids): BatchQuoteRequest Pydantic model in S3
    // uses instrument_ids as the field name (F-SEC-006: explicit field prevents
    // ambiguity with entity_id). Gateway was updated to match.
    const body = JSON.parse(calledInit?.body as string) as { instrument_ids: string[] };
    expect(body.instrument_ids).toEqual(["id-1", "id-2", "id-3"]);
  });

  it("serialises screener request correctly", async () => {
    const spy = mockFetch(200, { results: [], total: 0, offset: 0, limit: 20 });
    const gw = createGateway("token");
    await gw.runScreener({
      filters: [{ field: "pe_ratio", operator: "lt", value: 20 }],
      sort_by: "market_cap",
      sort_dir: "desc",
      limit: 20,
    });

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const body = JSON.parse(calledInit?.body as string) as {
      filters: Array<{ field: string; operator: string; value: number }>;
      sort_by: string;
    };
    expect(body.filters[0].field).toBe("pe_ratio");
    expect(body.sort_by).toBe("market_cap");
  });
});

// ── Error handling ────────────────────────────────────────────────────────

describe("createGateway() — error handling", () => {
  it("throws GatewayError on 401", async () => {
    mockFetch(401, { detail: "Authentication required" });
    const gw = createGateway("expired-token");

    await expect(gw.getPortfolios()).rejects.toThrow(GatewayError);
    await expect(gw.getPortfolios()).rejects.toHaveProperty("status", 401);
  });

  it("throws GatewayError on 503", async () => {
    mockFetch(503, { detail: "Service unavailable" });
    const gw = createGateway("token");

    await expect(gw.getMorningBrief()).rejects.toThrow(GatewayError);
  });

  it("throws GatewayError with error detail message", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: () => Promise.resolve({ detail: "Instrument not found" }),
    } as unknown as Response);

    const gw = createGateway("token");
    await expect(gw.getOHLCV("nonexistent-id")).rejects.toThrow(
      "Instrument not found",
    );
  });
});

// ── HTTP methods ─────────────────────────────────────────────────────────

describe("createGateway() — HTTP methods", () => {
  it("uses DELETE method for acknowledgeAlert", async () => {
    const spy = mockFetch(200, {});
    const gw = createGateway("token");
    await gw.acknowledgeAlert("alert-123");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    expect(calledInit?.method).toBe("DELETE");
  });

  it("uses DELETE method for deleteWatchlist", async () => {
    const spy = mockFetch(200, {});
    const gw = createGateway("token");
    await gw.deleteWatchlist("watchlist-456");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    expect(calledInit?.method).toBe("DELETE");
  });

  it("uses GET method for getPortfolios (default)", async () => {
    const spy = mockFetch(200, { items: [], total: 0, limit: 100, offset: 0 });
    const gw = createGateway("token");
    await gw.getPortfolios();

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    // GET requests don't need method explicitly — should be undefined or "GET"
    expect(calledInit?.method).toBeUndefined();
  });
});

// ── Response transformations ─────────────────────────────────────────────
//
// WHY THESE TESTS EXIST: The gateway transforms raw S9/S1/S3 API responses into
// the frontend types defined in types/api.ts. These transformations are the most
// critical code in the gateway — if a field mapping is wrong, components render
// blank or crash. Each test uses a realistic S1/S3 response shape (verified from
// the actual Pydantic schemas in the backend service code).

describe("createGateway() — response transformations", () => {
  it("getPortfolios() unwraps paginated response and maps id → portfolio_id", async () => {
    // Realistic S1 PaginatedResponse<PortfolioResponse> shape
    mockFetch(200, {
      items: [
        {
          id: "p-uuid-1",
          tenant_id: "t-uuid-1",
          owner_id: "u-uuid-1",
          name: "Demo Portfolio",
          currency: "USD",
          status: "active",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    const gw = createGateway("token");
    const portfolios = await gw.getPortfolios();

    // WHY these assertions: verify the id → portfolio_id mapping is correct
    // and all required frontend fields are populated
    expect(portfolios).toHaveLength(1);
    expect(portfolios[0].portfolio_id).toBe("p-uuid-1");
    expect(portfolios[0].name).toBe("Demo Portfolio");
    expect(portfolios[0].currency).toBe("USD");
    expect(portfolios[0].owner_id).toBe("u-uuid-1");
    expect(portfolios[0].created_at).toBe("2026-01-01T00:00:00Z");
    // updated_at defaults to created_at since S1 doesn't return it
    expect(portfolios[0].updated_at).toBe("2026-01-01T00:00:00Z");
  });

  it("getHoldings() wraps bare array into HoldingsResponse", async () => {
    // Realistic S1 list[HoldingResponse] — bare array with Decimal strings
    mockFetch(200, [
      {
        id: "h-uuid-1",
        portfolio_id: "p-uuid-1",
        instrument_id: "inst-uuid-1",
        quantity: "10.00000000",
        average_cost: "150.50000000",
        currency: "USD",
      },
    ]);
    const gw = createGateway("token");
    const result = await gw.getHoldings("p-uuid-1");

    // WHY: verify the wrapping and Decimal string → number conversion
    expect(result.portfolio_id).toBe("p-uuid-1");
    expect(result.holdings).toHaveLength(1);
    expect(result.holdings[0].holding_id).toBe("h-uuid-1");
    expect(result.holdings[0].quantity).toBe(10);
    expect(result.holdings[0].average_cost).toBe(150.5);
    // P&L fields should be null (computed client-side from live quotes)
    expect(result.total_value).toBeNull();
    expect(result.total_unrealised_pnl).toBeNull();
  });

  it("getHoldings() handles empty array gracefully", async () => {
    mockFetch(200, []);
    const gw = createGateway("token");
    const result = await gw.getHoldings("p-uuid-1");

    expect(result.portfolio_id).toBe("p-uuid-1");
    expect(result.holdings).toHaveLength(0);
  });

  it("getWatchlists() maps id → watchlist_id and user_id → owner_id", async () => {
    // Realistic S1 list[WatchlistResponse] — bare array
    mockFetch(200, [
      {
        id: "wl-uuid-1",
        tenant_id: "t-uuid-1",
        user_id: "u-uuid-1",
        name: "Tech Watchlist",
        status: "active",
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const gw = createGateway("token");
    const watchlists = await gw.getWatchlists();

    expect(watchlists).toHaveLength(1);
    expect(watchlists[0].watchlist_id).toBe("wl-uuid-1");
    expect(watchlists[0].owner_id).toBe("u-uuid-1");
    expect(watchlists[0].name).toBe("Tech Watchlist");
    // Members default to empty since list endpoint doesn't include them
    expect(watchlists[0].members).toEqual([]);
    expect(watchlists[0].member_count).toBe(0);
  });

  it("searchInstruments() transforms InstrumentListResponse to SearchResponse", async () => {
    // Realistic S3 InstrumentListResponse shape
    mockFetch(200, {
      items: [
        {
          id: "inst-uuid-1",
          security_id: "sec-1",
          symbol: "AAPL",
          exchange: "US",
          is_active: true,
          flags: { has_ohlcv: true, has_quotes: true, has_fundamentals: true },
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });
    const gw = createGateway();
    const result = await gw.searchInstruments("AAPL");

    expect(result.query).toBe("AAPL");
    expect(result.results).toHaveLength(1);
    expect(result.results[0].instrument_id).toBe("inst-uuid-1");
    expect(result.results[0].ticker).toBe("AAPL");
    expect(result.results[0].exchange).toBe("US");
    // Name synthesised from symbol + exchange since S3 has no name field
    expect(result.results[0].name).toBe("AAPL (US)");
    expect(result.results[0].type).toBe("equity");
  });

  it("getPredictionMarkets() transforms items → markets with outcome probabilities", async () => {
    // Realistic S3 PredictionMarketsListResponse shape
    mockFetch(200, {
      items: [
        {
          market_id: "pm-uuid-1",
          question: "Will BTC reach $100k by 2027?",
          outcomes: [
            { name: "Yes", token_id: "tok-yes", price: 0.65 },
            { name: "No", token_id: "tok-no", price: 0.35 },
          ],
          volume_24h: 125000,
          close_time: "2027-01-01T00:00:00Z",
          resolution_status: "open",
          resolved_answer: null,
          updated_at: "2026-04-01T12:00:00Z",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    const gw = createGateway("token");
    const result = await gw.getPredictionMarkets();

    expect(result.total).toBe(1);
    expect(result.markets).toHaveLength(1);
    expect(result.markets[0].title).toBe("Will BTC reach $100k by 2027?");
    expect(result.markets[0].yes_probability).toBe(0.65);
    expect(result.markets[0].no_probability).toBe(0.35);
    expect(result.markets[0].volume_usd).toBe(125000);
    expect(result.markets[0].status).toBe("open");
  });

  it("getTopMovers() transforms screener results to Mover[]", async () => {
    // Realistic S9 composed endpoint — returns raw screener results.
    // WHY 0.0523 (not 5.23): S3 daily_return is a decimal fraction (0.0523 = 5.23%).
    // BP-243: the transform multiplies by 100 so change_pct arrives as 5.23.
    mockFetch(200, {
      results: [
        {
          instrument_id: "inst-1",
          symbol: "NVDA",
          name: "NVIDIA Corp",
          exchange: "US",
          metrics: { daily_return: 0.0523, market_cap: 3200000000000 },
        },
      ],
      total: 1,
    });
    const gw = createGateway("token");
    const result = await gw.getTopMovers("gainers", 5);

    expect(result.type).toBe("gainers");
    expect(result.movers).toHaveLength(1);
    expect(result.movers[0].ticker).toBe("NVDA");
    expect(result.movers[0].name).toBe("NVIDIA Corp");
    expect(result.movers[0].change_pct).toBeCloseTo(5.23);
  });

  it("getTopMovers() passes through pre-shaped movers response", async () => {
    // If S9 is updated to return the correct shape directly, it should work too
    mockFetch(200, {
      movers: [{ instrument_id: "i-1", ticker: "TSLA", name: "Tesla", price: 250, change_pct: 3.5, volume: 80000000 }],
      type: "losers",
    });
    const gw = createGateway("token");
    const result = await gw.getTopMovers("losers", 5);

    expect(result.type).toBe("losers");
    expect(result.movers[0].ticker).toBe("TSLA");
    expect(result.movers[0].price).toBe(250);
  });

  it("getTransactions() unwraps paginated response and maps fields", async () => {
    // Realistic S1 PaginatedResponse<TransactionListItem>
    mockFetch(200, {
      items: [
        {
          id: "tx-uuid-1",
          portfolio_id: "p-uuid-1",
          instrument_id: "inst-uuid-1",
          transaction_type: "TRADE",
          direction: "BUY",
          quantity: "5.00000000",
          price: "150.25000000",
          fees: "1.00000000",
          currency: "USD",
          executed_at: "2026-04-01T10:00:00Z",
          external_ref: null,
          created_at: "2026-04-01T10:00:01Z",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });
    const gw = createGateway("token");
    const result = await gw.getTransactions("p-uuid-1");

    expect(result.total).toBe(1);
    expect(result.transactions).toHaveLength(1);
    expect(result.transactions[0].transaction_id).toBe("tx-uuid-1");
    expect(result.transactions[0].type).toBe("BUY");
    expect(result.transactions[0].quantity).toBe(5);
    expect(result.transactions[0].price).toBe(150.25);
    expect(result.transactions[0].fee).toBe(1);
  });
});

// ── Ranked news methods (PRD-0026) ────────────────────────────────────────
//
// WHY separate describe block: These methods changed return type from the legacy
// NewsResponse (Article[]) to RankedNewsResponse (RankedArticle[]). Tests verify:
// 1. Correct S9 path construction (route changed from S5 to S6 in Wave 7)
// 2. Query params forwarding (hours, limit, offset, min_display_score, routing_tier)
// 3. Entity ID is in the path (not a query param) for getEntityNews

describe("createGateway() — ranked news (PRD-0026)", () => {
  it("getTopNews() calls /api/v1/news/top with no params when empty", async () => {
    // WHY {articles: [], total: 0}: S6 RankedNewsResponse shape (no offset/limit field)
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway(); // no token — public endpoint
    await gw.getTopNews();

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/news/top");
  });

  it("getTopNews() forwards hours, limit, and min_display_score as query params", async () => {
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway();
    await gw.getTopNews({ hours: 48, limit: 10, min_display_score: 0.5 });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // All three params must appear in the query string
    expect(calledUrl).toContain("hours=48");
    expect(calledUrl).toContain("limit=10");
    expect(calledUrl).toContain("min_display_score=0.5");
  });

  it("getTopNews() forwards routing_tier filter", async () => {
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway();
    await gw.getTopNews({ routing_tier: "DEEP" });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("routing_tier=DEEP");
  });

  it("getTopNews() does not send Authorization header (public endpoint)", async () => {
    // WHY: news/top is public — no token required. Sending one is harmless but
    // tests ensure we don't accidentally gate it behind auth.
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway("my-token");
    await gw.getTopNews({ limit: 5 });

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBeUndefined();
  });

  it("getEntityNews() places entity_id in the URL path (not as a query param)", async () => {
    // WHY path param (not query): PRD-0026 §6.2 F-26 specifies the entity as a REST
    // path segment: GET /v1/news/entity/{entity_id}. Using a query param would violate
    // REST conventions and would be rejected by S9's route matcher.
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway("token");
    await gw.getEntityNews("entity-abc-123", { limit: 5 });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // Entity ID must be in the path
    expect(calledUrl).toContain("/v1/news/entity/entity-abc-123");
    // Entity ID must NOT appear as a query param
    expect(calledUrl).not.toContain("entity_id=");
    expect(calledUrl).toContain("limit=5");
  });

  it("getEntityNews() forwards order_by and date range params", async () => {
    const spy = mockFetch(200, { articles: [], total: 0 });
    const gw = createGateway("token");
    await gw.getEntityNews("e-1", {
      order_by: "published_at",
      start_date: "2026-04-01T00:00:00Z",
      end_date: "2026-04-22T00:00:00Z",
    });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("order_by=published_at");
    expect(calledUrl).toContain("start_date=2026-04-01T00%3A00%3A00Z");
  });

  it("getEntityNews() returns articles array from RankedNewsResponse", async () => {
    // Realistic S6 RankedNewsResponse — verifies the type passthrough
    const mockArticle = {
      article_id: "art-uuid-1",
      title: "Fed raises rates",
      url: "https://example.com/fed",
      published_at: "2026-04-22T10:00:00Z",
      source_type: "eodhd_news",
      source_name: "EODHD",
      routing_tier: "DEEP",
      routing_score: 0.85,
      market_impact_score: 0.72,
      llm_relevance_score: 0.91,
      display_relevance_score: 0.83,
      primary_entity_id: null,
      primary_entity_symbol: null,
      impact_windows: { day_t0: 0.03, day_t1: 0.05, day_t2: null, day_t5: null },
    };
    mockFetch(200, { articles: [mockArticle], total: 1 });
    const gw = createGateway("token");
    const result = await gw.getEntityNews("e-uuid-1");

    // WHY verify total not limit: RankedNewsResponse has no .limit field (unlike NewsResponse)
    expect(result.total).toBe(1);
    expect(result.articles).toHaveLength(1);
    expect(result.articles[0].article_id).toBe("art-uuid-1");
    // Verify the richer S6 fields are preserved through the gateway
    expect(result.articles[0].display_relevance_score).toBe(0.83);
    expect(result.articles[0].source_name).toBe("EODHD");
    expect(result.articles[0].impact_windows?.day_t0).toBe(0.03);
  });
});

// ── Fundamentals section + timeseries methods (PLAN-0041 Wave B-1) ────────────
//
// WHY THESE TESTS EXIST: Six new gateway methods wrap the S9 section proxy
// routes added in Wave A-1. Tests verify:
// 1. Correct S9 URL paths (wrong paths → silent data failure — instruments show "—")
// 2. Auth header forwarding (section endpoints require Bearer token)
// 3. Timeseries public endpoint sends NO auth header (different access pattern)
// 4. URL-encoding of instrument IDs preserves special characters

describe("createGateway() — fundamentals sections (PLAN-0041 Wave B-1)", () => {
  it("getTechnicals() calls /v1/fundamentals/{id}/technicals with auth", async () => {
    const spy = mockFetch(200, { security_id: "id-1", records: [] });
    const gw = createGateway("test-token");
    await gw.getTechnicals("inst-001");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/fundamentals/inst-001/technicals");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer test-token");
  });

  it("getShareStatistics() calls /v1/fundamentals/{id}/share-statistics with auth", async () => {
    const spy = mockFetch(200, { security_id: "id-1", records: [] });
    const gw = createGateway("test-token");
    await gw.getShareStatistics("inst-002");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/fundamentals/inst-002/share-statistics");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer test-token");
  });

  it("getInsiderTransactions() calls /v1/fundamentals/{id}/insider-transactions with auth", async () => {
    const spy = mockFetch(200, { security_id: "id-1", records: [] });
    const gw = createGateway("test-token");
    await gw.getInsiderTransactions("inst-003");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/fundamentals/inst-003/insider-transactions");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer test-token");
  });

  it("getEarningsHistory() calls /v1/fundamentals/{id}/earnings-annual-trend with auth", async () => {
    // WHY /earnings-annual-trend (not /earnings-trend): /earnings-trend maps to
    // EODHD's EarningsTrend section which contains FORWARD-LOOKING analyst consensus
    // estimates. /earnings-annual-trend contains historical per-fiscal-year EPS actuals
    // stored as {date, epsActual} records — what EarningsHistoryChart needs. Updated
    // from /earnings-trend in Wave D-3 after live data confirmed the wrong endpoint
    // was being called (0 historical records returned by /earnings-trend for AAPL).
    const spy = mockFetch(200, { security_id: "id-1", records: [] });
    const gw = createGateway("test-token");
    await gw.getEarningsHistory("inst-004");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/fundamentals/inst-004/earnings-annual-trend");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer test-token");
  });

  it("getSplitsDividends() calls /v1/fundamentals/{id}/splits-dividends with auth", async () => {
    const spy = mockFetch(200, { security_id: "id-1", records: [] });
    const gw = createGateway("test-token");
    await gw.getSplitsDividends("inst-005");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/fundamentals/inst-005/splits-dividends");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer test-token");
  });

  it("getFundamentalsTimeseries() builds correct query string with all params", async () => {
    const spy = mockFetch(200, { instrument_id: "inst-006", metric: "pe_ratio", data: [] });
    // WHY createGateway() with no token: timeseries is a public endpoint —
    // no Authorization header should be sent even when a token exists.
    const gw = createGateway("test-token");
    await gw.getFundamentalsTimeseries("inst-006", "pe_ratio", {
      start_date: "2024-01-01",
      end_date: "2025-01-01",
      period_type: "QUARTERLY",
      limit: 20,
    });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("/api/v1/fundamentals/timeseries");
    expect(calledUrl).toContain("instrument_id=inst-006");
    expect(calledUrl).toContain("metric=pe_ratio");
    expect(calledUrl).toContain("start_date=2024-01-01");
    expect(calledUrl).toContain("period_type=QUARTERLY");
    expect(calledUrl).toContain("limit=20");

    // WHY no Authorization: timeseries is a public endpoint served by S9 with
    // a system JWT (not user JWT). Sending a user Bearer token would be incorrect.
    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBeUndefined();
  });

  it("getFundamentalsTimeseries() omits optional params when not provided", async () => {
    const spy = mockFetch(200, { instrument_id: "inst-007", metric: "revenue", data: [] });
    const gw = createGateway();
    await gw.getFundamentalsTimeseries("inst-007", "revenue");

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toContain("instrument_id=inst-007");
    expect(calledUrl).toContain("metric=revenue");
    // WHY not contain these: optional params with undefined values must be omitted
    // entirely — URLSearchParams(undefined) produces "undefined" strings which
    // corrupt the S3 query.
    expect(calledUrl).not.toContain("start_date");
    expect(calledUrl).not.toContain("end_date");
    expect(calledUrl).not.toContain("period_type");
    expect(calledUrl).not.toContain("limit");
  });
});
