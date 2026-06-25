/**
 * features/portfolio/hooks/__tests__/useHoldingsSeries.test.ts
 *
 * WHY: Verifies the three core behavioural contracts of useHoldingsSeries:
 *  1. Happy path — batch response is returned as a Record<instrument_id, number[]>.
 *  2. Error path  — a 500 response surfaces isError=true and series={}.
 *  3. Disabled path — instrumentIds=[] must NOT fire the query.
 *
 * MOCKED: useAuth (auth context), global fetch (underlying primitive of apiFetch).
 *
 * WHY mock useAuth (not provide AuthProvider):
 *   The AuthProvider needs a full Zitadel/OIDC context tree. In unit tests we
 *   only care that the hook receives a token. A module-level vi.mock is the
 *   canonical approach used throughout this codebase (AnalyticsPeriodReturnsTable,
 *   ChatContextRail, IncomeStatementTable, etc.).
 *
 * WHY mock global fetch (not createGateway):
 *   useHoldingsSeries calls apiFetch from @/lib/api/_client, NOT createGateway.
 *   apiFetch ultimately calls the browser fetch() global. Stubbing fetch gives
 *   a clean interception point without coupling the test to the internal call path.
 *
 * WHY real @tanstack/react-query (not mocked):
 *   We're testing the HOOK — its enabled guard, staleTime, error handling, and
 *   return value mapping all flow through TanStack Query. Mocking it would bypass
 *   exactly what we want to validate.
 *
 * WHY retry: false on the test QueryClient:
 *   useHoldingsSeries sets retry:1. The test QueryClient overrides it to false so
 *   error tests resolve immediately without triggering a retry delay that would
 *   time out under waitFor's 1000ms default.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";

// ── Auth stub ─────────────────────────────────────────────────────────────────
// WHY: see file-level "WHY mock useAuth".
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── SUT ───────────────────────────────────────────────────────────────────────
// WHY imported AFTER vi.mock: Vitest hoists vi.mock to the top of the file, but
// explicit ordering documents the intent and prevents confusion when reading the
// test file sequentially.
import { useHoldingsSeries } from "../useHoldingsSeries";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeWrapper — creates a fresh QueryClient per test.
 *
 * WHY new QueryClient per test: TanStack Query caches responses in memory.
 * A shared client would let a successful-path test's cache bleed into the
 * error-path test, making the error test a no-op. Fresh client = clean cache.
 *
 * WHY retry: false: see file-level "WHY retry: false on the test QueryClient".
 */
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  // WHY React.createElement (not JSX): this is a .ts file; JSX transform
  // requires .tsx. createElement is semantically equivalent.
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: qc }, children);
  };
}

/**
 * mockFetch — stubs globalThis.fetch to return a JSON response.
 *
 * WHY Response constructor (not plain object): apiFetch calls response.json()
 * on the resolved value. A plain `{ ok: true, json: vi.fn() }` works for some
 * paths but the Response class is more faithful to the real runtime shape.
 */
function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useHoldingsSeries", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it("returns series keyed by instrument_id on a successful batch response", async () => {
    // Arrange: mock the batch sparkline endpoint with two instruments.
    // WHY these IDs: arbitrary but deterministic. Tests should not depend on
    // real UUIDs so future fixtures can reuse them without confusion.
    const id1 = "aaaa0000-0000-7000-8000-000000000001";
    const id2 = "bbbb0000-0000-7000-8000-000000000002";
    const mockSeries: Record<string, number[]> = {
      [id1]: [100, 102, 101, 105, 107, 106, 108, 110, 109, 111, 113, 112, 115, 116],
      [id2]: [50, 51, 52, 53, 54, 53, 55, 56, 57, 58, 59, 60, 61, 62],
    };
    mockFetch({ data: mockSeries });

    // Act
    const { result } = renderHook(
      () => useHoldingsSeries([id1, id2]),
      { wrapper: makeWrapper() },
    );

    // Assert: wait for the async query to settle.
    // WHY waitFor (not just checking result.current): useQuery is async.
    // The hook starts in isLoading=true; we must wait for the queryFn to
    // resolve before asserting the settled state.
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isError).toBe(false);

    // WHY assert both keys: confirms the hook maps the full response.data
    // Record rather than only the first entry or a partial merge.
    expect(result.current.series[id1]).toEqual(mockSeries[id1]);
    expect(result.current.series[id2]).toEqual(mockSeries[id2]);
  });

  it("returns empty object and isError=true when the batch endpoint returns 500", async () => {
    // Arrange: simulate a gateway error from S9.
    // WHY 500 (not 404): 500 is the realistic failure mode for a batch endpoint
    // under load. 404 would hit the apiFetch "malformed path" guard instead.
    mockFetch({ detail: "Internal Server Error" }, 500);

    const { result } = renderHook(
      () => useHoldingsSeries(["id-a", "id-b"]),
      { wrapper: makeWrapper() },
    );

    // WHY isError=true in waitFor: the query transitions through isLoading
    // before settling to isError. waitFor polls until the predicate passes.
    //
    // WHY timeout: 5000ms: useHoldingsSeries sets retry:1. TanStack Query uses
    // exponential back-off starting at 1000ms for the first retry, which means
    // the query takes ≈1s + network time before settling to isError. The default
    // waitFor timeout of 1000ms isn't long enough to observe the final state.
    // 5000ms gives comfortable headroom for the one retry cycle.
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 5000 });

    // WHY series={} on error: SparklineCellRenderer must not throw on missing
    // keys. Returning {} (not undefined) means callers can still do
    // `series[id]` and get undefined, which renders as "—".
    expect(result.current.series).toEqual({});
    expect(result.current.isLoading).toBe(false);
  });

  it("does not fire the query when instrumentIds is empty", async () => {
    // WHY this test: the `enabled: instrumentIds.length > 0` guard prevents
    // a malformed `?instrument_ids=&days=14` request. If the guard broke,
    // the gateway would return 422 and we'd be leaking a useless request per
    // portfolio page mount.
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(
      () => useHoldingsSeries([]),
      { wrapper: makeWrapper() },
    );

    // WHY a small timeout: there's no async event to waitFor — the query
    // never starts, so we assert the ABSENCE of a network call. We must
    // wait long enough for any async microtasks to flush before concluding
    // fetch was not called.
    await new Promise((resolve) => setTimeout(resolve, 50));

    // WHY not called: the `enabled` guard should have blocked the queryFn.
    expect(fetchSpy).not.toHaveBeenCalled();

    // Series stays empty and no error is raised.
    expect(result.current.series).toEqual({});
    expect(result.current.isError).toBe(false);
    expect(result.current.isLoading).toBe(false);
  });
});
