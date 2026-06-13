/**
 * __tests__/dashboard-w4.test.tsx — Wave-4 dashboard density/usefulness changes
 *
 * WHY THIS EXISTS (user report 2026-06-12): Wave 4 reworked five dashboard
 * surfaces. These tests pin the new contracts:
 *   1. MarketBreadthMini — derives advancers/decliners from the SAME cached
 *      sector-heatmap data (no new endpoint), renders the up/down bar + counts,
 *      and shows a named empty state when there's no sector data.
 *   2. PortfolioNewsWidget — is now PORTFOLIO-SCOPED: it fans out one
 *      /v1/news/entity/{id} call per holding and aggregates, instead of the
 *      old global /v1/news/top feed. We pin that getEntityNews is called per
 *      holding and that getTopNews is NOT the source.
 *   3. WatchlistQuickViewWidget (Top Positions) — client-side infinite scroll:
 *      shows PAGE_SIZE rows initially, reveals the next page when the
 *      IntersectionObserver sentinel intersects.
 *   4. MorningBriefCard — renders the live v4.2 markdown narrative as a clean
 *      structured brief (the redundant "## Details" wrapper stripped, the inner
 *      "**Market Snapshot**" section heading preserved), instead of raw
 *      "## Details" chrome.
 *
 * (The Sector 7+6 compact grid is pinned in sector-heatmap-overflow.test.tsx.)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { BriefingResponse } from "@/types/api";

// ── Capturing IntersectionObserver stub (drive infinite scroll) ───────────────
// jsdom has no IntersectionObserver; the global vitest.setup stub is a no-op.
// We install a CAPTURING stub here so the top-positions test can FIRE an
// intersection event and assert the next page is revealed.
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

// ── Next.js navigation mock ───────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — shared mutable object across all widgets ───────────────────
const gatewayMocks = {
  // Sector heatmap (drives both SectorHeatmapWidget AND MarketBreadthMini).
  getMarketHeatmap: vi.fn().mockResolvedValue({ sectors: [] }),
  getTopMovers: vi.fn().mockResolvedValue({ movers: [], type: "gainers" as const }),
  getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
  getCompanyOverview: vi.fn().mockResolvedValue({ instrument: null, quote: null }),
  // Portfolio + holdings + per-entity news (PortfolioNewsWidget).
  getPortfolios: vi.fn().mockResolvedValue([]),
  getHoldings: vi.fn().mockResolvedValue({ portfolio_id: "p1", holdings: [] }),
  getEntityNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  getTopNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  // Quotes + sparklines (WatchlistQuickViewWidget).
  getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
  getMarketSparklines: vi.fn().mockResolvedValue({}),
  getMorningBrief: vi.fn(),
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

// ── Component imports (after vi.mock) ─────────────────────────────────────────
import { MarketBreadthMini } from "@/components/dashboard/MarketBreadthMini";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { WatchlistQuickViewWidget } from "@/components/dashboard/WatchlistQuickViewWidget";
import { MorningBriefCard } from "@/components/dashboard/MorningBriefCard";

// ── Helpers ───────────────────────────────────────────────────────────────────
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Build a holdings fixture with N entity-bearing positions (NVDA, AAPL, …). */
function makeHoldings(n: number) {
  const tickers = ["NVDA", "AAPL", "MSFT", "META", "AMZN", "JPM", "GOOGL", "TSLA", "DIS", "NFLX", "KO", "PEP"];
  return {
    portfolio_id: "p1",
    holdings: Array.from({ length: n }, (_, i) => ({
      holding_id: `h-${i}`,
      portfolio_id: "p1",
      instrument_id: `ins-${i}`,
      entity_id: `ent-${i}`,
      ticker: tickers[i % tickers.length],
      name: `${tickers[i % tickers.length]} Inc`,
      quantity: 10 + i,
      average_cost: 100,
      current_price: 100 + i, // distinct value per holding so the sort is stable
      currency: "USD",
      asset_class: "equity",
    })),
  };
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
  // Reset mocks to the empty universe before each test.
  Object.values(gatewayMocks).forEach((m) => m.mockReset());
  gatewayMocks.getMarketHeatmap.mockResolvedValue({ sectors: [] });
  gatewayMocks.getTopMovers.mockResolvedValue({ movers: [], type: "gainers" });
  gatewayMocks.getCompanyOverviewsBatch.mockResolvedValue({});
  gatewayMocks.getCompanyOverview.mockResolvedValue({ instrument: null, quote: null });
  gatewayMocks.getPortfolios.mockResolvedValue([]);
  gatewayMocks.getHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
  gatewayMocks.getEntityNews.mockResolvedValue({ articles: [], total: 0 });
  gatewayMocks.getTopNews.mockResolvedValue({ articles: [], total: 0 });
  gatewayMocks.getBatchQuotes.mockResolvedValue({ quotes: {} });
  gatewayMocks.getMarketSparklines.mockResolvedValue({});
});

afterEach(() => {
  globalThis.IntersectionObserver = realIO;
});

// ── 1. MarketBreadthMini ──────────────────────────────────────────────────────

describe("MarketBreadthMini — sector breadth from shared heatmap data", () => {
  it("counts advancers/decliners and renders the up/down bar + % positive", async () => {
    // 13 sectors: 9 up, 4 down → 69% positive, bar up-segment ≈ 69%.
    gatewayMocks.getMarketHeatmap.mockResolvedValue({
      sectors: [
        { name: "Industrials", change_pct: 2.46, instrument_count: 10 },
        { name: "Materials", change_pct: 2.23, instrument_count: 10 },
        { name: "Consumer Cyclical", change_pct: 1.89, instrument_count: 10 },
        { name: "ETF", change_pct: 1.81, instrument_count: 10 },
        { name: "Technology", change_pct: 1.55, instrument_count: 10 },
        { name: "Healthcare", change_pct: 0.89, instrument_count: 10 },
        { name: "Financial Services", change_pct: 0.71, instrument_count: 10 },
        { name: "Utilities", change_pct: 0.66, instrument_count: 10 },
        { name: "Consumer Defensive", change_pct: 0.39, instrument_count: 10 },
        { name: "Communication Services", change_pct: -0.12, instrument_count: 10 },
        { name: "Real Estate", change_pct: -0.1, instrument_count: 10 },
        { name: "Crypto", change_pct: -0.83, instrument_count: 10 },
        { name: "Energy", change_pct: -1.21, instrument_count: 10 },
      ],
    });

    render(<MarketBreadthMini />, { wrapper });

    // Headline: 9 up of 13 decisive = 69%.
    await waitFor(() => {
      expect(screen.getByText("69%")).toBeInTheDocument();
    });
    // Advancers / decliners counts.
    expect(screen.getByText("9 up")).toBeInTheDocument();
    expect(screen.getByText("4 down")).toBeInTheDocument();
    // The up segment's width is proportional (9/13 ≈ 69.2%).
    const up = screen.getByTestId("breadth-up-segment");
    expect(up.style.width).toMatch(/^69\./);
  });

  it("renders the named empty state when the heatmap has no sectors", async () => {
    gatewayMocks.getMarketHeatmap.mockResolvedValue({ sectors: [] });
    render(<MarketBreadthMini />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No breadth data")).toBeInTheDocument();
    });
  });
});

// ── 2. PortfolioNewsWidget — portfolio-scoped news ────────────────────────────

describe("PortfolioNewsWidget — portfolio-scoped (per-holding) news", () => {
  it("fans out getEntityNews per holding (NOT the global getTopNews feed)", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue(ONE_PORTFOLIO);
    gatewayMocks.getHoldings.mockResolvedValue(makeHoldings(3));
    // Each entity returns one article tied to that holding.
    gatewayMocks.getEntityNews.mockImplementation((entityId: string) =>
      Promise.resolve({
        articles: [
          {
            article_id: `art-${entityId}`,
            title: `Headline for ${entityId}`,
            url: `https://example.com/${entityId}`,
            published_at: new Date().toISOString(),
            source_type: "eodhd_news",
            routing_tier: "HIGH",
            market_impact_score: 0.7,
            display_relevance_score: 0.7,
            primary_entity_id: entityId,
            primary_entity_symbol: null,
            impact_windows: null,
          },
        ],
        total: 1,
      }),
    );

    render(<PortfolioNewsWidget />, { wrapper });

    // A portfolio-relevant headline (tied to a held entity) appears.
    await waitFor(() => {
      expect(screen.getByText("Headline for ent-0")).toBeInTheDocument();
    });
    // getEntityNews was called once per holding (3), and the GLOBAL feed
    // getTopNews was NOT used as the source.
    expect(gatewayMocks.getEntityNews).toHaveBeenCalledTimes(3);
    expect(gatewayMocks.getTopNews).not.toHaveBeenCalled();
  });

  it("shows the no-holdings empty state when the portfolio has no holdings", async () => {
    gatewayMocks.getPortfolios.mockResolvedValue([]);
    gatewayMocks.getHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
    render(<PortfolioNewsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No holdings to track")).toBeInTheDocument();
    });
  });
});

// ── 3. WatchlistQuickViewWidget — infinite scroll ─────────────────────────────

describe("WatchlistQuickViewWidget — Top Positions infinite scroll", () => {
  it("shows PAGE_SIZE rows initially, then reveals more when the sentinel intersects", async () => {
    // Install the capturing IO stub for THIS test so we can drive intersection.
    globalThis.IntersectionObserver =
      CapturingIntersectionObserver as unknown as typeof IntersectionObserver;

    gatewayMocks.getPortfolios.mockResolvedValue(ONE_PORTFOLIO);
    // 40 > PAGE_SIZE(30) so the first block leaves rows behind for the sentinel.
    gatewayMocks.getHoldings.mockResolvedValue(makeHoldings(40));

    render(<WatchlistQuickViewWidget />, { wrapper });

    // First page: 30 rows. Each row's accessible name is "Open <TICKER> detail page".
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /detail page$/i }).length,
      ).toBe(30);
    });
    // The "scroll for more" sentinel caption confirms there are more rows.
    expect(screen.getByText(/30 of 40 · scroll for more/i)).toBeInTheDocument();

    // Fire an intersection on the sentinel → reveal the next PAGE_SIZE rows.
    act(() => {
      observerCallbacks.forEach((cb) => cb([{ isIntersecting: true }]));
    });

    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: /detail page$/i }).length,
      ).toBe(40);
    });
    // All revealed → footer flips to the "all N positions" caption.
    expect(screen.getByText(/all 40 positions/i)).toBeInTheDocument();
  });
});

// ── 4. MorningBriefCard — v4.2 narrative structured render ─────────────────────

/** A live-shaped v4.2 brief: everything in `narrative`, no sections/summary. */
function v42Brief(): BriefingResponse {
  return {
    narrative:
      "## Details\n" +
      "**Market Snapshot**\n" +
      "- SPY +1.29%, QQQ +2.43%, VIX +11.83% to 21.38 — risk-on in broad indices\n\n" +
      "**Your Portfolio Today**\n" +
      "- MSFT -2.31% pre-mkt (-$276) — largest drag; investigate before open\n\n" +
      "**Macro Today**\n" +
      "- No scheduled macro releases today\n",
    summary: null,
    summary_paragraph: null,
    risk_summary: null,
    entity_mentions: [],
    citations: [],
    sections: [],
    generated_at: new Date().toISOString(),
    cached: false,
    entity_id: null,
    confidence: 0,
    lead: null,
  } as unknown as BriefingResponse;
}

describe("MorningBriefCard — v4.2 narrative renders structured (not raw chrome)", () => {
  it("renders the Market Snapshot content and strips the redundant '## Details' wrapper", async () => {
    gatewayMocks.getMorningBrief.mockResolvedValue(v42Brief());

    render(<MorningBriefCard />, { wrapper });

    // The real market content renders (proves the brief body is shown, not a
    // "Market data unavailable" placeholder).
    await waitFor(() => {
      expect(screen.getByText(/SPY \+1\.29%/)).toBeInTheDocument();
    });
    // The inner section heading is preserved as a structured sub-head…
    expect(screen.getByText("Market Snapshot")).toBeInTheDocument();
    // …but the redundant top-level "Details" wrapper heading is stripped (the
    // card already labels itself "Morning Briefing"). No standalone "Details".
    expect(screen.queryByText("Details")).not.toBeInTheDocument();
  });
});
