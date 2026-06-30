/**
 * lib/api/__tests__/chat.test.ts — Unit tests for the chat gateway module's
 * getCompanyOverviewByTicker() (Wave 2, frontend-rework sprint).
 *
 * WHY THESE TESTS EXIST:
 * The by-ticker overview call is the rail's "ONE request per entity card"
 * contract (Wave-1 backend endpoint). Three behaviours must hold:
 *   1. URL construction — GET /v1/companies/by-ticker/{ticker}/overview,
 *      with the ticker URL-encoded (defensive: extractor output is plain
 *      A-Z, but the API boundary must not trust that forever).
 *   2. 404 → null — an unresolvable ticker yields NO card, not an error
 *      banner (the rail's fail-silent contract).
 *   3. Non-404 errors still throw — a 500 must keep TanStack Query's
 *      error/retry semantics intact.
 *
 * Strategy: mock global fetch() and assert URL + return value, same approach
 * as search.test.ts.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createChatApi, normalizeCitation } from "../chat";
import { GatewayError } from "../_client";

function mockFetch(status: number, body: unknown = {}) {
  const mockResponse = {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    // apiFetch may read text() on error paths for diagnostics.
    text: () => Promise.resolve(JSON.stringify(body)),
    body: null,
  };
  return vi
    .spyOn(global, "fetch")
    .mockResolvedValue(mockResponse as unknown as Response);
}

const MOCK_OVERVIEW = {
  instrument: { instrument_id: "i-1", ticker: "AAPL", name: "Apple Inc" },
  quote: { price: 315.2, change_pct: -7.93, volume: 44_186_784 },
  fundamentals: { market_cap: 4.3e12, pe_ratio: 35.5 },
  ohlcv: { bars: [] },
};

describe("createChatApi().getCompanyOverviewByTicker", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("GETs /v1/companies/by-ticker/{ticker}/overview and returns the overview", async () => {
    const spy = mockFetch(200, MOCK_OVERVIEW);
    const api = createChatApi("tok");

    const result = await api.getCompanyOverviewByTicker("AAPL");

    expect(spy).toHaveBeenCalledTimes(1);
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/v1/companies/by-ticker/AAPL/overview");
    expect(result).toEqual(MOCK_OVERVIEW);
  });

  it("URL-encodes the ticker path segment", async () => {
    const spy = mockFetch(200, MOCK_OVERVIEW);
    const api = createChatApi("tok");

    await api.getCompanyOverviewByTicker("BRK/B");

    const url = String(spy.mock.calls[0][0]);
    // "/" must not create an extra path segment.
    expect(url).toContain("/v1/companies/by-ticker/BRK%2FB/overview");
  });

  it("maps 404 (unresolvable ticker) to null — the rail's fail-silent contract", async () => {
    mockFetch(404, { detail: "not found" });
    const api = createChatApi("tok");

    await expect(api.getCompanyOverviewByTicker("ZZZZZ")).resolves.toBeNull();
  });

  it("rethrows non-404 failures so TanStack Query keeps error semantics", async () => {
    mockFetch(500, { detail: "boom" });
    const api = createChatApi("tok");

    await expect(api.getCompanyOverviewByTicker("AAPL")).rejects.toBeInstanceOf(
      GatewayError,
    );
  });
});

describe("normalizeCitation", () => {
  it("maps the canonical rag-chat shape onto the legacy contract", () => {
    // rag-chat emits {id, source_name, confidence, ...}; the chip reads
    // {article_id, source, relevance_score, ...}. Normalization bridges them.
    const out = normalizeCitation({
      id: "cit-1",
      source_name: "Reuters",
      confidence: 0.82,
      title: "NVDA beats",
      url: "https://news.example.com/nvda",
    });
    expect(out.article_id).toBe("cit-1");
    expect(out.source).toBe("Reuters");
    expect(out.relevance_score).toBe(0.82);
  });

  it("threads published_at through so the chip can show the date", () => {
    const out = normalizeCitation({
      id: "cit-2",
      source_name: "Bloomberg",
      published_at: "2026-06-30T08:00:00Z",
    });
    expect(out.published_at).toBe("2026-06-30T08:00:00Z");
  });

  it("defaults published_at to null when the source omits it (KG items)", () => {
    const out = normalizeCitation({ id: "kg-1", item_type: "relation" });
    expect(out.published_at).toBeNull();
  });
});
