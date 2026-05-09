/**
 * lib/api/__tests__/search.test.ts — Unit tests for searchDocuments() gateway method.
 *
 * WHY THESE TESTS EXIST (PLAN-0064 W6 T-W6-1-04):
 * The URL construction for searchDocuments() has several subtle correctness requirements:
 * 1. entity_id repeated params must use `append`, not `set` (set overwrites earlier values)
 * 2. `q` must be URL-encoded (special chars like quotes, OR, - go into websearch_to_tsquery)
 * 3. ISO date strings must arrive verbatim (no re-parsing on the client)
 * 4. Non-2xx responses must throw GatewayError (not silently return undefined)
 *
 * Strategy: mock global fetch() to capture the exact URL the method constructs,
 * then assert on the URL string. This is the same approach as gateway.test.ts.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createSearchApi } from "../search";
import type { SearchDocumentsResponse } from "@/types/api";
import { GatewayError } from "../_client";

// ── Test helpers ──────────────────────────────────────────────────────────────

/**
 * mockFetch — replace global.fetch with a spy that returns the given status/body.
 * Returns the spy so tests can interrogate which URL was called.
 */
function mockFetch(status: number, body: unknown = {}) {
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

/**
 * Minimal SearchDocumentsResponse for mocking 200 responses.
 * The test only needs to verify the URL, not the response shape.
 */
const _MOCK_RESPONSE: SearchDocumentsResponse = {
  query: "apple",
  total: 0,
  page: 1,
  page_size: 25,
  has_more: false,
  results: [],
  facets: [],
  latency_ms: 10,
};

beforeEach(() => {
  // Reset all mocks between tests — prevent state leakage across assertions
  vi.restoreAllMocks();
});

// ── searchDocuments URL construction ─────────────────────────────────────────

describe("searchDocuments() — URL construction", () => {
  it("test_searchDocuments_buildsCorrectUrlWithSingleEntityFilter", async () => {
    /**
     * WHY: A single entity_id must appear as `entity_id=<uuid>` in the URL.
     * If the URL is wrong, FastAPI rejects the request with 422 (missing list param).
     */
    const spy = mockFetch(200, _MOCK_RESPONSE);
    const api = createSearchApi("test-token");

    await api.searchDocuments({
      q: "apple earnings",
      entity_ids: ["018f1e2a-0000-7000-8000-000000000001"],
    });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // URLSearchParams URL-encodes the value; UUID chars are safe so no encoding needed
    expect(calledUrl).toContain("entity_id=018f1e2a-0000-7000-8000-000000000001");
    expect(calledUrl).toContain("q=apple+earnings");  // URLSearchParams encodes spaces as +
  });

  it("test_searchDocuments_buildsCorrectUrlWithMultipleEntityFilters", async () => {
    /**
     * WHY: Multiple entity_ids must appear as REPEATED params in the URL:
     * `entity_id=uuid1&entity_id=uuid2`. FastAPI's `list[UUID]` parameter type
     * expects exactly this form — a single `entity_id=uuid1,uuid2` would fail.
     *
     * The URL encoding is produced by `url.append("entity_id", id)` in search.ts.
     * This test is the regression guard that confirms we use append (not set).
     */
    const spy = mockFetch(200, _MOCK_RESPONSE);
    const api = createSearchApi("test-token");

    await api.searchDocuments({
      q: "revenue",
      entity_ids: [
        "018f1e2a-0000-7000-8000-000000000001",
        "018f1e2a-0000-7000-8000-000000000002",
      ],
    });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // Both entity_ids must appear as separate repeated params
    expect(calledUrl).toContain("entity_id=018f1e2a-0000-7000-8000-000000000001");
    expect(calledUrl).toContain("entity_id=018f1e2a-0000-7000-8000-000000000002");
    // Sanity: they must both be in the same URL string
    const entityMatches = calledUrl.match(/entity_id=/g);
    expect(entityMatches).toHaveLength(2);
  });

  it("test_searchDocuments_throwsOnNon2xx", async () => {
    /**
     * WHY: Non-2xx responses must throw GatewayError. Without this, a 401 or 503
     * from S9 would silently return undefined, causing blank search panels with no
     * user-visible error. GatewayError.status lets TanStack Query surface the right
     * error message (e.g. "sign in again" on 401, "try later" on 503).
     */
    mockFetch(401, { detail: "Unauthorized" });
    const api = createSearchApi(undefined);  // no token → 401

    await expect(
      api.searchDocuments({ q: "test" }),
    ).rejects.toBeInstanceOf(GatewayError);
  });

  it("test_searchDocuments_serialisesDatesAsIso8601", async () => {
    /**
     * WHY: date_from and date_to are passed as ISO 8601 strings (not JS Date objects).
     * ISO strings are unambiguous for the Python backend's datetime parser. If we
     * passed a Date object, URLSearchParams would call .toString() → locale-dependent
     * formatting → backend 422.
     */
    const spy = mockFetch(200, _MOCK_RESPONSE);
    const api = createSearchApi("test-token");

    await api.searchDocuments({
      q: "earnings",
      date_from: "2026-01-01T00:00:00Z",
      date_to: "2026-05-09T23:59:59Z",
    });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // The ISO strings must appear verbatim in the URL (URL-encoded colons/Ts are fine)
    expect(calledUrl).toContain("date_from=");
    expect(calledUrl).toContain("date_to=");
    // Decode and check the values are the original ISO strings
    const urlObj = new URL(calledUrl, "http://test");
    expect(urlObj.searchParams.get("date_from")).toBe("2026-01-01T00:00:00Z");
    expect(urlObj.searchParams.get("date_to")).toBe("2026-05-09T23:59:59Z");
  });

  it("test_searchDocuments_urlEncodesQ", async () => {
    /**
     * WHY: q can contain characters that websearch_to_tsquery accepts: quoted phrases
     * ("apple earnings"), OR operator, - negation. URLSearchParams must percent-encode
     * these so the URL is valid. Without encoding, `"apple earnings"` would produce a
     * malformed URL that proxies reject before reaching S6.
     *
     * URLSearchParams encodes " as %22 and space as +. We verify that the raw q value
     * can be reconstructed from the URL (roundtrip), confirming no data loss.
     */
    const spy = mockFetch(200, _MOCK_RESPONSE);
    const api = createSearchApi("test-token");

    const rawQ = '"apple earnings" OR revenue';
    await api.searchDocuments({ q: rawQ });

    const calledUrl = (spy.mock.calls[0] as [string, unknown])[0] as string;
    // The URL must contain a q param
    expect(calledUrl).toContain("q=");
    // Roundtrip: decode back to the original string (proves no data loss during encoding)
    const urlObj = new URL(calledUrl, "http://test");
    expect(urlObj.searchParams.get("q")).toBe(rawQ);
  });
});
