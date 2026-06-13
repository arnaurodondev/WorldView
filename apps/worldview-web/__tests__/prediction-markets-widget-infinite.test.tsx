/**
 * __tests__/prediction-markets-widget-infinite.test.tsx — dashboard widget
 * infinite scroll + server-side category filtering (2026-06-10).
 *
 * PINS:
 *   1. initial fetch is page 1 (offset 0, limit 15) of the open universe
 *   2. the IntersectionObserver sentinel triggers fetchNextPage → offset 15,
 *      and the new rows APPEND (not replace)
 *   3. category pills push the filter server-side via `?category=` (the old
 *      client-side categorize() filter was the "filtering doesn't work" bug)
 *   4. the sentinel disappears once the (filter-scoped) universe is exhausted
 *
 * IntersectionObserver cannot be driven by jsdom — we install a CAPTURING
 * stub that records the callback so tests can fire intersection manually
 * (same approach as alert-history-tab.test.tsx).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { PredictionMarket } from "@/types/api";

// ── Capturing IntersectionObserver stub ────────────────────────────────────

type IOCallback = (entries: Array<{ isIntersecting: boolean }>) => void;
let observerCallbacks: IOCallback[] = [];

class CapturingIntersectionObserver {
  callback: IOCallback;
  constructor(cb: IOCallback) {
    this.callback = cb;
    observerCallbacks.push(cb);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

const realIO = globalThis.IntersectionObserver;

// ── Gateway mocks ──────────────────────────────────────────────────────────

const mockGetPredictionMarkets = vi.fn();
const mockGetPredictionMarketCategories = vi.fn();
const mockGetPredictionMarketHistory = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getPredictionMarkets: mockGetPredictionMarkets,
    getPredictionMarketCategories: mockGetPredictionMarketCategories,
    getPredictionMarketHistory: mockGetPredictionMarketHistory,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";

// ── Fixtures ───────────────────────────────────────────────────────────────

function makeMarket(i: number, overrides: Partial<PredictionMarket> = {}): PredictionMarket {
  return {
    market_id: `m-${i}`,
    title: `Market question ${i}?`,
    description: "",
    yes_probability: 0.5,
    no_probability: 0.5,
    volume_usd: 1000,
    status: "open",
    resolution_date: "2026-12-31T23:59:00Z",
    entity_ids: [],
    tickers: [],
    source: "polymarket",
    url: "",
    market_slug: null,
    category: "politics",
    updated_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

/** Param-aware mock backend: 20 open markets, 7 of them crypto. */
function installBackend() {
  const universe = Array.from({ length: 40 }, (_, i) =>
    makeMarket(i, { category: i < 7 ? "crypto" : "politics" }),
  );
  mockGetPredictionMarkets.mockImplementation(
    async (params: { limit?: number; offset?: number; category?: string }) => {
      const filtered = params?.category
        ? universe.filter((m) => m.category === params.category)
        : universe;
      const offset = params?.offset ?? 0;
      const limit = params?.limit ?? 30;
      return { markets: filtered.slice(offset, offset + limit), total: filtered.length };
    },
  );
  mockGetPredictionMarketCategories.mockResolvedValue({
    items: [
      { category: "politics", count: 13 },
      { category: "crypto", count: 7 },
    ],
    total: 20,
  });
  mockGetPredictionMarketHistory.mockResolvedValue({ market_id: "x", points: [] });
}

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  observerCallbacks = [];
  globalThis.IntersectionObserver =
    CapturingIntersectionObserver as unknown as typeof IntersectionObserver;
  window.IntersectionObserver =
    CapturingIntersectionObserver as unknown as typeof IntersectionObserver;
  installBackend();
});

afterEach(() => {
  globalThis.IntersectionObserver = realIO;
  window.IntersectionObserver = realIO;
});

/** Fire every captured observer callback as "sentinel is intersecting". */
async function intersectSentinel() {
  await act(async () => {
    observerCallbacks.forEach((cb) => cb([{ isIntersecting: true }]));
  });
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("PredictionMarketsWidget — infinite scroll + server-side filter", () => {
  it("fetches page 1 (offset 0) and renders the loaded rows", async () => {
    render(<PredictionMarketsWidget />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Market question 0?")).toBeInTheDocument();
    });
    expect(mockGetPredictionMarkets).toHaveBeenCalledWith(
      expect.objectContaining({ status: "open", offset: 0, category: undefined }),
    );
    // First page = 30 rows (PAGE_SIZE), not the old top-3 slice.
    expect(screen.getByText("Market question 29?")).toBeInTheDocument();
    expect(screen.queryByText("Market question 30?")).not.toBeInTheDocument();
  });

  it("intersecting the sentinel fetches the next page and APPENDS rows", async () => {
    render(<PredictionMarketsWidget />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("Market question 29?"));

    // The sentinel rendered (40 total > 30 loaded → hasNextPage).
    expect(screen.getByTestId("prediction-markets-sentinel")).toBeInTheDocument();

    await intersectSentinel();

    // Page 2 requested at offset 30 …
    await waitFor(() => {
      expect(mockGetPredictionMarkets).toHaveBeenCalledWith(
        expect.objectContaining({ offset: 30 }),
      );
    });
    // … and appended after the existing rows (page 1 still present).
    await waitFor(() => {
      expect(screen.getByText("Market question 39?")).toBeInTheDocument();
    });
    expect(screen.getByText("Market question 0?")).toBeInTheDocument();
  });

  it("removes the sentinel once the full universe is loaded", async () => {
    render(<PredictionMarketsWidget />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("Market question 29?"));

    await intersectSentinel();
    await waitFor(() => screen.getByText("Market question 39?"));

    // 40/40 loaded → no next page → sentinel unmounts (observer stops).
    expect(screen.queryByTestId("prediction-markets-sentinel")).not.toBeInTheDocument();
  });

  it("category pill pushes the filter server-side (?category=crypto)", async () => {
    render(<PredictionMarketsWidget />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("Market question 0?"));

    // The crypto pill renders from the counts endpoint (count 7 > 0).
    const cryptoPill = await screen.findByRole("button", { name: /crypto/i });
    fireEvent.click(cryptoPill);

    // The refetch carries the category param down to the gateway — the old
    // implementation never sent it (client-side keyword filter ≠ pill counts).
    await waitFor(() => {
      expect(mockGetPredictionMarkets).toHaveBeenCalledWith(
        expect.objectContaining({ category: "crypto", offset: 0 }),
      );
    });
    // Only the 7 crypto rows render; politics rows are gone.
    await waitFor(() => {
      expect(screen.getByText("Market question 6?")).toBeInTheDocument();
      expect(screen.queryByText("Market question 7?")).not.toBeInTheDocument();
    });
    // 7 ≤ 15 → whole bucket fits in one page → no sentinel under the filter.
    expect(screen.queryByTestId("prediction-markets-sentinel")).not.toBeInTheDocument();
  });
});
