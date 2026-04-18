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
    const spy = mockFetch(200, []);
    const gw = createGateway("test-token");
    await gw.getPortfolios();

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    expect(calledUrl).toBe("/api/v1/portfolios");
  });

  it("constructs correct holdings URL with portfolio ID", async () => {
    const spy = mockFetch(200, { portfolio_id: "p-1", holdings: [] });
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
    const spy = mockFetch(200, { results: [], query: "apple" });
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
    const spy = mockFetch(200, []);
    const gw = createGateway("my-bearer-token");
    await gw.getPortfolios();

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBe("Bearer my-bearer-token");
  });

  it("does not inject Authorization when no token", async () => {
    const spy = mockFetch(200, { results: [], query: "" });
    const gw = createGateway(); // no token
    await gw.searchInstruments("apple");

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    const headers = calledInit?.headers as Record<string, string>;
    expect(headers?.["Authorization"]).toBeUndefined();
  });

  it("does not inject Authorization when null token", async () => {
    const spy = mockFetch(200, { results: [], query: "" });
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
    const body = JSON.parse(calledInit?.body as string) as { ids: string[] };
    expect(body.ids).toEqual(["id-1", "id-2", "id-3"]);
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
    const spy = mockFetch(200, []);
    const gw = createGateway("token");
    await gw.getPortfolios();

    const calledInit = (spy.mock.calls[0] as [string, RequestInit])[1];
    // GET requests don't need method explicitly — should be undefined or "GET"
    expect(calledInit?.method).toBeUndefined();
  });
});
