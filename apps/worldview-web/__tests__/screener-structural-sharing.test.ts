/**
 * __tests__/screener-structural-sharing.test.ts — Round-4 item 3c: row data
 * identity must be stable across refetches when the payload is unchanged.
 *
 * WHY THIS EXISTS: the gateway transformer (lib/api/screener.ts runScreener)
 * builds BRAND-NEW row objects on every call — it maps the backend's nested
 * `metrics: {…}` shape into flat ScreenerResult objects inside the queryFn.
 * The page's whole render pipeline (accumulator merge → applyClientFilters
 * memo → AG Grid getRowId/rowData diff → memoised MiniChart rows) leans on
 * row REFERENCE stability to skip work.
 *
 * The reason fresh objects are still fine: the mapping happens inside the
 * QUERYFN (not in render), so TanStack Query's structural sharing
 * (replaceEqualDeep) compares the fresh result against the cached one and —
 * when deep-equal — RETURNS THE OLD REFERENCES. This test pins that contract
 * with the real transformer in the loop, so a future refactor that moves the
 * mapping into render (e.g. a `.map()` over `data.results` in the component
 * body) or disables structuralSharing on the query gets caught: the
 * unchanged-payload identity assertions below would start failing.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { createScreenerApi } from "@/lib/api/screener";
import type { ScreenerRequest, ScreenerResponse } from "@/types/api";

// ── Fetch stub ────────────────────────────────────────────────────────────────
// Each call returns a FRESH deep clone of the payload — exactly what a real
// backend does (new JSON body per response). Reusing one shared object would
// trivially pass the identity assertions and prove nothing.
function stubFetchSequence(payloads: unknown[]) {
  let call = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () => {
      const payload = payloads[Math.min(call, payloads.length - 1)];
      call += 1;
      return {
        ok: true,
        status: 200,
        json: async () => structuredClone(payload),
      };
    }),
  );
}

const BACKEND_PAYLOAD = {
  results: [
    {
      instrument_id: "01900000-0000-7000-8000-000000000001",
      ticker: "AAPL",
      name: "Apple Inc.",
      sector: "Information Technology",
      metrics: { pe_ratio: 28.5, market_cap: 3_000_000_000_000 },
    },
    {
      instrument_id: "01900000-0000-7000-8000-000000000002",
      ticker: "TSLA",
      name: "Tesla Inc.",
      sector: "Consumer Discretionary",
      metrics: { pe_ratio: 65.2, market_cap: 750_000_000_000 },
    },
  ],
  total: 2,
};

// A non-default filter so runScreener takes the POST path (the GET default
// path is a separate endpoint shape — irrelevant to the sharing mechanics).
const REQUEST: ScreenerRequest = {
  filters: [{ metric: "pe_ratio", min_value: 1 }] as ScreenerRequest["filters"],
  limit: 50,
  offset: 0,
};

const QUERY_KEY = ["screener", "structural-sharing-test", 0] as const;

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("screener query — TanStack structural sharing (Round 4 item 3c)", () => {
  it("keeps row object identity across a refetch with an unchanged payload", async () => {
    stubFetchSequence([BACKEND_PAYLOAD, BACKEND_PAYLOAD]);
    const api = createScreenerApi("token");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const queryFn = () => api.runScreener(REQUEST);

    const first = await qc.fetchQuery({ queryKey: QUERY_KEY, queryFn });
    // Force a real second network round-trip on the same key.
    await qc.refetchQueries({ queryKey: QUERY_KEY, exact: true });
    const second = qc.getQueryData<ScreenerResponse>(QUERY_KEY);

    // Two fetches actually happened (the transformer built fresh objects twice)…
    expect(vi.mocked(fetch).mock.calls.length).toBe(2);
    // …but structural sharing collapsed the deep-equal result back onto the
    // ORIGINAL references — top-level response AND each row object.
    expect(second).toBe(first);
    expect(second?.results[0]).toBe(first.results[0]);
    expect(second?.results[1]).toBe(first.results[1]);
  });

  it("preserves identity of UNCHANGED rows when only one row's data changes", async () => {
    // Second payload: TSLA's P/E moved; AAPL identical. Structural sharing is
    // per-node — the unchanged AAPL row must keep its reference (so its
    // memoised cells skip re-render) while TSLA gets a new one.
    const changed = structuredClone(BACKEND_PAYLOAD);
    changed.results[1].metrics.pe_ratio = 70.1;
    stubFetchSequence([BACKEND_PAYLOAD, changed]);

    const api = createScreenerApi("token");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const queryFn = () => api.runScreener(REQUEST);

    const first = await qc.fetchQuery({ queryKey: QUERY_KEY, queryFn });
    await qc.refetchQueries({ queryKey: QUERY_KEY, exact: true });
    const second = qc.getQueryData<ScreenerResponse>(QUERY_KEY);

    expect(second).not.toBe(first); // something changed → new top-level ref
    expect(second?.results[0]).toBe(first.results[0]); // AAPL unchanged → shared
    expect(second?.results[1]).not.toBe(first.results[1]); // TSLA changed → new
    expect(second?.results[1].pe_ratio).toBe(70.1);
  });
});
