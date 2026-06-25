/**
 * __tests__/movers-pagination.test.tsx — W4 movers pagination (blocks of 30)
 *
 * WHY THIS EXISTS (user report 2026-06-12 "on pagination I would display in
 * blocks of 30"): the three movers lists used to be hard-capped — TopMovers at
 * 10 rows, Holdings/Watchlist movers at 5 per column — with no way to see
 * deeper movers. They now paginate in blocks of 30:
 *
 *   1. TopMovers (MARKET tab) — SERVER pagination via useInfiniteQuery +
 *      `getTopMovers(type, 30, "1D", offset)`. The IntersectionObserver sentinel
 *      fetches the NEXT page (offset 30) when scrolled into view.
 *   2. HoldingsMoversWidget — CLIENT windowing: the full holdings list is
 *      fetched once, ranked, and the gainers/losers columns reveal 30 per side
 *      per sentinel intersection.
 *   3. WatchlistMoversWidget — CLIENT windowing over the insights movers array,
 *      same 30-per-side block reveal.
 *
 * The Top Positions (WatchlistQuickViewWidget) infinite scroll is pinned
 * separately in dashboard-w4.test.tsx (it shipped in W4 task 5).
 *
 * TEST STRATEGY: a CAPTURING IntersectionObserver stub records the observer
 * callbacks so each test can FIRE an intersection event and assert the next
 * block is fetched/revealed. jsdom has no real IntersectionObserver.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Capturing IntersectionObserver stub ───────────────────────────────────────
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

/** Fire an intersection on every currently-registered sentinel observer. */
function fireIntersect() {
  act(() => {
    observerCallbacks.forEach((cb) => cb([{ isIntersecting: true }]));
  });
}

// ── Mocks ──────────────────────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token", isAuthenticated: true })),
}));

// useResolvedPortfolioId follows the active-portfolio chip; for tests just
// resolve to the first portfolio (the Holdings widget passes the list in).
vi.mock("@/hooks/useResolvedPortfolioId", () => ({
  useResolvedPortfolioId: (
    portfolios: Array<{ portfolio_id: string }> | undefined,
  ) => portfolios?.[0]?.portfolio_id ?? null,
}));

const gatewayMocks = {
  getTopMovers: vi.fn(),
  getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
  getMarketSparklines: vi.fn().mockResolvedValue({}),
  getPortfolios: vi.fn().mockResolvedValue([]),
  getHoldings: vi.fn().mockResolvedValue({ portfolio_id: "p1", holdings: [] }),
  getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
  getWatchlists: vi.fn().mockResolvedValue([]),
  getWatchlistInsights: vi.fn(),
  getOHLCV: vi.fn(),
};

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayMocks),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Component imports (after vi.mock) ──────────────────────────────────────────
import { TopMovers } from "@/components/dashboard/TopMovers";
import { HoldingsMoversWidget } from "@/components/dashboard/HoldingsMoversWidget";
import { WatchlistMoversWidget } from "@/components/dashboard/WatchlistMoversWidget";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const ONE_PORTFOLIO = [
  {
    portfolio_id: "p1",
    name: "Main",
    currency: "USD",
    owner_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

beforeEach(() => {
  observerCallbacks = [];
  globalThis.IntersectionObserver =
    CapturingIntersectionObserver as unknown as typeof IntersectionObserver;
  Object.values(gatewayMocks).forEach((m) => m.mockReset?.());
  gatewayMocks.getCompanyOverviewsBatch.mockResolvedValue({});
  gatewayMocks.getMarketSparklines.mockResolvedValue({});
  gatewayMocks.getPortfolios.mockResolvedValue([]);
  gatewayMocks.getHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
  gatewayMocks.getBatchQuotes.mockResolvedValue({ quotes: {} });
  gatewayMocks.getWatchlists.mockResolvedValue([]);
});

afterEach(() => {
  globalThis.IntersectionObserver = realIO;
});

// ── 1. TopMovers (MARKET tab) — server pagination, blocks of 30 ───────────────

describe("TopMovers — MARKET tab server-side pagination (blocks of 30)", () => {
  /** Build a one-page response of `n` gainer rows with sequential ids. */
  function moversPage(n: number, startIdx: number) {
    return {
      type: "gainers" as const,
      movers: Array.from({ length: n }, (_, i) => {
        const idx = startIdx + i;
        return {
          instrument_id: `ins-${idx}`,
          ticker: `T${idx}`,
          name: `Co ${idx}`,
          price: 0,
          change_pct: 5 - idx * 0.01,
          volume: null,
        };
      }),
    };
  }

  it("fetches the first 30, then requests offset 30 when the sentinel intersects", async () => {
    // Page 0: a FULL block of 30 (so getNextPageParam keeps paging).
    // Page 1: a short block of 10 (signals the end of the universe).
    gatewayMocks.getTopMovers.mockImplementation(
      (_type: string, _limit: number, _period: string, offset: number) =>
        Promise.resolve(offset === 0 ? moversPage(30, 0) : moversPage(10, 30)),
    );

    render(<TopMovers />, { wrapper });

    // First page: 30 mover rows (each row is a role=button "Navigate to … page").
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /Navigate to .* instrument page/i }).length,
      ).toBe(30);
    });
    // The first call used limit 30 + offset 0.
    expect(gatewayMocks.getTopMovers).toHaveBeenCalledWith("gainers", 30, "1D", 0);

    // Fire the sentinel → fetchNextPage with offset 30.
    fireIntersect();

    await waitFor(() => {
      expect(gatewayMocks.getTopMovers).toHaveBeenCalledWith("gainers", 30, "1D", 30);
    });
    // Both pages flattened → 40 rows total.
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /Navigate to .* instrument page/i }).length,
      ).toBe(40);
    });
  });

  it("does NOT page further when the first block is short (< 30)", async () => {
    // A single short page of 12 → no next page, sentinel never rendered.
    gatewayMocks.getTopMovers.mockResolvedValue(moversPage(12, 0));

    render(<TopMovers />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /Navigate to .* instrument page/i }).length,
      ).toBe(12);
    });
    // No sentinel rendered (hasNextPage is false for a short page).
    expect(screen.queryByTestId("top-movers-sentinel")).not.toBeInTheDocument();

    // Firing any stray observer must NOT trigger another fetch.
    fireIntersect();
    expect(gatewayMocks.getTopMovers).toHaveBeenCalledTimes(1);
  });
});

// ── 2. HoldingsMoversWidget — client windowing, blocks of 30 ──────────────────

describe("HoldingsMoversWidget — client-side windowing (blocks of 30)", () => {
  /** Build holdings + a batch-quotes map giving each a distinct +/- change. */
  function holdingsAndQuotes(gainerCount: number, loserCount: number) {
    const holdings = [
      ...Array.from({ length: gainerCount }, (_, i) => ({
        holding_id: `gh-${i}`,
        portfolio_id: "p1",
        instrument_id: `g-${i}`,
        entity_id: `ge-${i}`,
        ticker: `G${i}`,
        name: `Gainer ${i}`,
        quantity: 10,
        average_cost: 100,
        current_price: 110,
        currency: "USD",
        asset_class: "equity",
      })),
      ...Array.from({ length: loserCount }, (_, i) => ({
        holding_id: `lh-${i}`,
        portfolio_id: "p1",
        instrument_id: `l-${i}`,
        entity_id: `le-${i}`,
        ticker: `L${i}`,
        name: `Loser ${i}`,
        quantity: 10,
        average_cost: 100,
        current_price: 90,
        currency: "USD",
        asset_class: "equity",
      })),
    ];
    const quotes: Record<string, { price: number; change: number; change_pct: number }> = {};
    for (let i = 0; i < gainerCount; i++) {
      // Distinct positive change_pct so the abs-rank order is stable.
      quotes[`g-${i}`] = { price: 110, change: 1, change_pct: 5 - i * 0.01 };
    }
    for (let i = 0; i < loserCount; i++) {
      quotes[`l-${i}`] = { price: 90, change: -1, change_pct: -(5 - i * 0.01) };
    }
    return {
      holdings: { portfolio_id: "p1", holdings },
      quotes: { quotes },
    };
  }

  it("shows 30 gainers initially and reveals more after the sentinel intersects", async () => {
    // 40 gainers, 2 losers → first window caps gainers at 30; 10 remain.
    const fx = holdingsAndQuotes(40, 2);
    gatewayMocks.getPortfolios.mockResolvedValue(ONE_PORTFOLIO);
    gatewayMocks.getHoldings.mockResolvedValue(fx.holdings);
    gatewayMocks.getBatchQuotes.mockResolvedValue(fx.quotes);

    render(<HoldingsMoversWidget />, { wrapper });

    // First window: 30 gainer rows. Holdings rows accessible name: "Open <T> instrument page".
    await waitFor(() => {
      const rows = screen.getAllByRole("button", { name: /Open G\d+ instrument page/i });
      expect(rows.length).toBe(30);
    });
    // The "scroll for more" caption (30/40 gainers shown) is present.
    expect(screen.getByText(/scroll for more/i)).toBeInTheDocument();

    // Reveal the next block.
    fireIntersect();

    await waitFor(() => {
      const rows = screen.getAllByRole("button", { name: /Open G\d+ instrument page/i });
      expect(rows.length).toBe(40); // all 40 gainers now visible
    });
    // Everything revealed → "all shown" caption, sentinel gone.
    expect(screen.getByText(/all shown/i)).toBeInTheDocument();
    expect(screen.queryByTestId("holdings-movers-sentinel")).not.toBeInTheDocument();
  });

  it("does not render a sentinel when both columns fit in the first block", async () => {
    const fx = holdingsAndQuotes(5, 5);
    gatewayMocks.getPortfolios.mockResolvedValue(ONE_PORTFOLIO);
    gatewayMocks.getHoldings.mockResolvedValue(fx.holdings);
    gatewayMocks.getBatchQuotes.mockResolvedValue(fx.quotes);

    render(<HoldingsMoversWidget />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /Open G\d+ instrument page/i }).length,
      ).toBe(5);
    });
    // 5 + 5 < 30 → no pagination chrome at all.
    expect(screen.queryByTestId("holdings-movers-sentinel")).not.toBeInTheDocument();
    expect(screen.queryByText(/scroll for more/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/all shown/i)).not.toBeInTheDocument();
  });
});

// ── 3. WatchlistMoversWidget — client windowing, blocks of 30 ─────────────────

describe("WatchlistMoversWidget — client-side windowing (blocks of 30)", () => {
  function insightsWith(gainerCount: number, loserCount: number) {
    const movers = [
      ...Array.from({ length: gainerCount }, (_, i) => ({
        instrument_id: `g-${i}`,
        entity_id: `ge-${i}`,
        ticker: `G${i}`,
        name: `Gainer ${i}`,
        sector: "Information Technology",
        price: 100,
        change_pct: 5 - i * 0.01,
        news_count_24h: 0,
        has_active_alert: false,
        top_news_title: null,
        top_news_url: null,
      })),
      ...Array.from({ length: loserCount }, (_, i) => ({
        instrument_id: `l-${i}`,
        entity_id: `le-${i}`,
        ticker: `L${i}`,
        name: `Loser ${i}`,
        sector: "Information Technology",
        price: 100,
        change_pct: -(5 - i * 0.01),
        news_count_24h: 0,
        has_active_alert: false,
        top_news_title: null,
        top_news_url: null,
      })),
    ];
    return {
      watchlist_id: "wl-1",
      members_count: movers.length,
      weighted_return_1d: 0.5,
      alerts_count: 0,
      sectors: [],
      biggest_news: null,
      movers,
    };
  }

  it("shows 30 gainers initially and reveals more after the sentinel intersects", async () => {
    gatewayMocks.getWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    gatewayMocks.getWatchlistInsights.mockResolvedValue(insightsWith(40, 2));

    render(<WatchlistMoversWidget />, { wrapper });

    // WatchlistMoverRow accessible name pattern (ticker-first nav button).
    await waitFor(() => {
      const rows = screen.getAllByRole("button", { name: /^Open G\d+/i });
      expect(rows.length).toBe(30);
    });
    expect(screen.getByText(/scroll for more/i)).toBeInTheDocument();

    fireIntersect();

    await waitFor(() => {
      const rows = screen.getAllByRole("button", { name: /^Open G\d+/i });
      expect(rows.length).toBe(40);
    });
    expect(screen.getByText(/all shown/i)).toBeInTheDocument();
    expect(screen.queryByTestId("watchlist-movers-sentinel")).not.toBeInTheDocument();
  });

  it("does not render a sentinel when both columns fit in the first block", async () => {
    gatewayMocks.getWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    gatewayMocks.getWatchlistInsights.mockResolvedValue(insightsWith(4, 4));

    render(<WatchlistMoversWidget />, { wrapper });

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /^Open G\d+/i }).length).toBe(4);
    });
    expect(screen.queryByTestId("watchlist-movers-sentinel")).not.toBeInTheDocument();
    expect(screen.queryByText(/scroll for more/i)).not.toBeInTheDocument();
  });
});
