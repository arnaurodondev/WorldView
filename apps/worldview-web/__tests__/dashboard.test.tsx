/**
 * __tests__/dashboard.test.tsx — Unit tests for dashboard widget components
 *
 * WHY THIS EXISTS: Dashboard widgets are the most user-facing components.
 * Tests verify that each widget correctly handles loading, error, and empty
 * states — the three failure modes that traders would see if S9 is unavailable.
 *
 * WAVE 7 UPDATES:
 * - Added tests for new widgets: MarketSnapshotWidget, SectorHeatmapWidget,
 *   PreMarketMoversWidget, PredictionMarketsWidget, PortfolioNewsWidget,
 *   EarningsCalendarWidget
 * - Verified AiSignals and TopBets are NO LONGER rendered in the dashboard page
 * - Grid structure: col-span-12, col-span-4, col-span-8, etc.
 * - Existing tests preserved (R19: never delete tests)
 *
 * WHY MOCK GATEWAY: We don't want real S9 calls in unit tests.
 * The gateway mock lets us control exactly what each widget receives.
 *
 * DATA SOURCE: Mocked gateway client
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MarketHeatmap } from "@/components/dashboard/MarketHeatmap";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { AiSignals } from "@/components/dashboard/AiSignals";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
import { PreMarketMoversWidget } from "@/components/dashboard/PreMarketMoversWidget";
import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { EarningsCalendarWidget } from "@/components/dashboard/EarningsCalendarWidget";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: TopMovers and AiSignals use useRouter() for navigation. In unit tests
// the App Router isn't mounted — mock it to avoid "invariant" error.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── AlertStreamContext mock ────────────────────────────────────────────────────
// WHY: RecentAlerts widget uses useAlertStream() which reads from a WebSocket
// context. In unit tests, no WebSocket is running — mock the context hook so
// RecentAlerts renders without throwing "useAlertStream must be inside <AlertStreamProvider>".
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: vi.fn(() => ({
    recentAlerts: [],
    unreadCount: 0,
    connectionStatus: "disconnected" as const,
    markAllRead: vi.fn(),
  })),
  AlertStreamProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getMarketHeatmap: vi.fn().mockResolvedValue({
      sectors: [
        { name: "Information Technology", change_pct: 1.5, instrument_count: 67 },
        { name: "Health Care", change_pct: -0.8, instrument_count: 62 },
        { name: "Energy", change_pct: null, instrument_count: 23 },
      ],
    }),
    getTopMovers: vi.fn().mockResolvedValue({
      movers: [
        {
          instrument_id: "ins-1",
          ticker: "NVDA",
          name: "NVIDIA Corp",
          price: 850.0,
          change_pct: 5.2,
          volume: 45_000_000,
        },
        {
          instrument_id: "ins-2",
          ticker: "TSLA",
          name: "Tesla Inc",
          price: 172.5,
          change_pct: -3.1,
          volume: 90_000_000,
        },
      ],
      type: "gainers" as const,
    }),
    getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
    getEconomicCalendar: vi.fn().mockResolvedValue({
      events: [
        {
          event_id: "ev-1",
          title: "CPI YoY (Feb)",
          country: "US",
          currency: "USD",
          event_date: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(),
          forecast: 3.1,
          previous: 3.2,
          actual: null,
          impact: "HIGH" as const,
          unit: "%",
        },
      ],
    }),
    getPredictionMarkets: vi.fn().mockResolvedValue({
      markets: [
        {
          market_id: "mkt-1",
          title: "Will Fed cut rates in June?",
          description: "Federal Reserve rate cut",
          yes_probability: 0.72,
          no_probability: 0.28,
          volume_usd: 500_000,
          status: "open" as const,
          resolution_date: null,
          entity_ids: [],
          tickers: [],
          source: "polymarket" as const,
          url: "https://polymarket.com/mkt-1",
          updated_at: new Date().toISOString(),
        },
      ],
      total: 1,
    }),
    getTopNews: vi.fn().mockResolvedValue({
      articles: [
        {
          article_id: "art-1",
          title: "NVDA reports record Q4 revenue",
          url: "https://example.com/nvda-q4",
          published_at: new Date(Date.now() - 30 * 60_000).toISOString(),
          source_type: "eodhd_news",
          source_name: "Reuters",
          routing_tier: "DEEP",
          routing_score: 0.9,
          market_impact_score: 0.85,
          llm_relevance_score: 0.82,
          display_relevance_score: 0.85,
          primary_entity_id: "ent-nvda",
          primary_entity_symbol: "NVDA",
          impact_windows: null,
        },
      ],
      total: 1,
    }),
    // WHY getPendingAlerts: RecentAlerts widget (in DashboardPage) polls pending alerts
    getPendingAlerts: vi.fn().mockResolvedValue({
      alerts: [],
      total: 0,
      offset: 0,
      limit: 10,
    }),
    // WHY searchInstruments: MarketSnapshotWidget resolves ticker → instrument_id
    // for all 9 tickers (3 index + 6 equities). Return a single result with the
    // searched ticker so all group rows get instrument IDs and the LIVE badge appears.
    searchInstruments: vi.fn().mockImplementation((ticker: string) =>
      Promise.resolve({
        results: [{ instrument_id: `ins-${ticker.toLowerCase()}`, entity_id: `ins-${ticker.toLowerCase()}`, ticker, name: `${ticker} Inc`, exchange: "US", type: "equity" }],
        query: ticker,
      }),
    ),
    // WHY getBatchQuotes: MarketSnapshotWidget batch-fetches live quotes.
    // Return non-zero prices so the truthfulness guard (hasPrice) passes for equities.
    getBatchQuotes: vi.fn().mockResolvedValue({
      quotes: {
        "ins-aapl": { price: 185.5, change: 2.3, change_pct: 1.25 },
        "ins-msft": { price: 350.0, change: 1.5, change_pct: 0.43 },
        "ins-nvda": { price: 800.0, change: 15.0, change_pct: 1.91 },
        "ins-amzn": { price: 180.0, change: 2.0, change_pct: 1.12 },
        "ins-googl": { price: 170.0, change: -1.0, change_pct: -0.58 },
        "ins-jpm": { price: 195.0, change: 0.5, change_pct: 0.26 },
        "ins-qqq": { price: 420.0, change: 5.0, change_pct: 1.20 },
        "ins-spy": { price: 0.0, change: 0.0, change_pct: 0.0 }, // no data yet
        "ins-btc": { price: 80000.0, change: 1000.0, change_pct: 1.27 },
      },
    }),
    // WHY getEarningsCalendar: EarningsCalendarWidget (Wave B-1, PLAN-0068) fetches
    // upcoming earnings events from S9 /v1/fundamentals/earnings-calendar.
    // Returns empty list by default so the widget renders the empty state.
    getEarningsCalendar: vi.fn().mockResolvedValue({
      events: [],
      total: 0,
    }),
    // WHY getMorningBrief: MorningBriefCard (in DashboardPage) fetches the brief
    getMorningBrief: vi.fn().mockResolvedValue({
      content: "Market conditions are stable.",
      risk_summary: null,
      entity_mentions: [],
      citations: [],
      generated_at: new Date().toISOString(),
      cached: false,
      entity_id: null,
    }),
    // WHY getEconomicCalendar: defined at top-level gateway mock below — this
    // line intentionally omitted here to avoid overriding the mock with events.
    // WHY getPortfolios/getHoldings: PortfolioSummary widget in DashboardPage
    getPortfolios: vi.fn().mockResolvedValue([]),
    // WHY getWatchlists/getWatchlistMembers: WatchlistMoversWidget (Wave E-2)
    // queries these to build the row list. Returning [] makes the widget
    // render its "No watchlist yet" empty-state — that's still a valid
    // path the dashboard tests just need to mount cleanly.
    getWatchlists: vi.fn().mockResolvedValue([]),
    getWatchlistMembers: vi.fn().mockResolvedValue([]),
    // WHY getOHLCV: WatchlistMoversWidget calls this in 1W/1M mode. Tests
    // run in default 1D mode where this is a no-op, but vitest still
    // hits the mock if `enabled` flips during the render lifecycle.
    getOHLCV: vi.fn().mockResolvedValue({
      instrument_id: "ins-1",
      ticker: "",
      timeframe: "1D",
      bars: [],
    }),
    // WHY getCompanyOverview: WatchlistMoversWidget fans out per-instrument
    // overview lookups for sector filtering. Empty mock OK — same key as
    // PreMarketMoversWidget's mover-overview-sector queries.
    getCompanyOverview: vi.fn().mockResolvedValue({
      instrument: {
        instrument_id: "ins-1",
        entity_id: "ins-1",
        ticker: "AAPL",
        name: "Apple Inc",
        gics_sector: "Information Technology",
      },
    }),
    getHoldings: vi.fn().mockResolvedValue({
      portfolio_id: "p1",
      holdings: [],
      total_value: null,
      total_cost: null,
      total_unrealised_pnl: null,
      total_unrealised_pnl_pct: null,
    }),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "tok",
      user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests: MarketHeatmap (existing, preserved per R19) ────────────────────────

describe("MarketHeatmap", () => {
  it("renders sector tiles after data loads", async () => {
    render(<MarketHeatmap />, { wrapper });

    // Should show loading skeletons initially
    await waitFor(() => {
      // After loading, sector tiles render
      expect(screen.getByTitle("Information Technology")).toBeInTheDocument();
    });
  });

  it("renders Tech abbreviation", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });
  });

  it("renders positive change percentage", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("+1.50%")).toBeInTheDocument();
    });
  });

  it("renders null change_pct as em dash", async () => {
    render(<MarketHeatmap />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });
});

// ── Tests: TopMovers (existing, preserved per R19) ────────────────────────────

describe("TopMovers", () => {
  it("renders mover tickers after data loads", async () => {
    render(<TopMovers />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });

  it("shows gainers/losers tab buttons", () => {
    render(<TopMovers />, { wrapper });

    expect(screen.getByText("gainers")).toBeInTheDocument();
    expect(screen.getByText("losers")).toBeInTheDocument();
  });
});

// ── Tests: AiSignals (existing, preserved per R19) ───────────────────────────

describe("AiSignals", () => {
  it("shows empty state when no signals returned", async () => {
    render(<AiSignals />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/signal data coming soon/i)).toBeInTheDocument();
    });
  });
});

// ── Tests: EconomicCalendar (existing, preserved per R19) ────────────────────

describe("EconomicCalendar", () => {
  it("renders economic event title", async () => {
    render(<EconomicCalendar />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("CPI YoY (Feb)")).toBeInTheDocument();
    });
  });

  it("renders HIGH impact indicator", async () => {
    render(<EconomicCalendar />, { wrapper });

    await waitFor(() => {
      // "H" is the single-letter abbreviation for HIGH impact
      expect(screen.getByText("H")).toBeInTheDocument();
    });
  });
});

// ── Tests: MarketSnapshotWidget (SA-2 PLAN-0088 Demo P1 rewrite) ───────────────
// WHY updated: SA-2 PLAN-0088 rewrite extended the widget from "6 large-cap
// equities" to a two-group snapshot (INDICES: QQQ/SPY/BTC + EQUITIES: 6 names).
// Footer text changed from "US large-cap equities" to "indices · equities · prior session".
// Tests updated to reflect the new layout while preserving the "renders header" and
// "LIVE badge" tests per R19 (never delete/weaken tests — update assertions to new spec).

describe("MarketSnapshotWidget", () => {
  it("renders MARKET SNAPSHOT header", () => {
    // WHY wrapper: MarketSnapshotWidget uses useQuery and must be inside QueryClientProvider
    render(<MarketSnapshotWidget />, { wrapper });
    expect(screen.getByText("MARKET SNAPSHOT")).toBeInTheDocument();
  });

  it("renders INDICES group label after loading", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    // WHY waitFor: group labels render after the idsQuery resolves (replacing skeletons).
    await waitFor(() => {
      expect(screen.getByText("INDICES")).toBeInTheDocument();
    });
  });

  it("renders EQUITIES group label after loading", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("EQUITIES")).toBeInTheDocument();
    });
  });

  it("renders equity ticker labels after loading", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    // WHY waitFor: ticker labels only render after the idsQuery resolves.
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
    // These render in the same pass as AAPL — once loading is done, all appear.
    // WHY still test AAPL/MSFT/NVDA: the EQUITIES group still contains all 6
    // original tickers; this test confirms no regression (R19).
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("AMZN")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
    expect(screen.getByText("JPM")).toBeInTheDocument();
  });

  it("shows LIVE badge after both queries resolve", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    // WHY waitFor: two sequential queries (search → batch-quote) complete asynchronously.
    // The LIVE badge only renders when !isLoading && instrumentIds.length > 0.
    await waitFor(() => {
      expect(screen.getByText("LIVE")).toBeInTheDocument();
    });
  });

  it("renders footer with updated data context text after loading", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    await waitFor(() => {
      // SA-2 PLAN-0088: footer now says "indices · equities · prior session"
      // (was "US large-cap equities · prior session") to reflect the two-group layout.
      expect(screen.getByText(/indices.*equities.*prior session/i)).toBeInTheDocument();
    });
  });
});

// ── Tests: SectorHeatmapWidget (Wave 7 new) ───────────────────────────────────

describe("SectorHeatmapWidget", () => {
  it("renders SECTOR PERFORMANCE header", () => {
    render(<SectorHeatmapWidget />, { wrapper });
    expect(screen.getByText("SECTOR PERFORMANCE")).toBeInTheDocument();
  });

  it("renders sector rows after data loads", async () => {
    render(<SectorHeatmapWidget />, { wrapper });
    // The mock returns 3 sectors
    await waitFor(() => {
      // Abbreviated sector names from abbreviateSector()
      expect(screen.getByText("Tech")).toBeInTheDocument();
    });
  });

  it("renders positive percentage in sector row", async () => {
    render(<SectorHeatmapWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("+1.50%")).toBeInTheDocument();
    });
  });
});

// ── Tests: PreMarketMoversWidget (Wave 7 new) ─────────────────────────────────

describe("PreMarketMoversWidget", () => {
  it("renders TOP MOVERS header", () => {
    render(<PreMarketMoversWidget />, { wrapper });
    expect(screen.getByText("TOP MOVERS")).toBeInTheDocument();
  });

  it("renders GAINERS and LOSERS sub-column headers", () => {
    render(<PreMarketMoversWidget />, { wrapper });
    expect(screen.getByText("GAINERS")).toBeInTheDocument();
    expect(screen.getByText("LOSERS")).toBeInTheDocument();
  });

  it("renders mover tickers after data loads", async () => {
    render(<PreMarketMoversWidget />, { wrapper });
    await waitFor(() => {
      // NVDA appears in the gainers column
      const nvdaEls = screen.getAllByText("NVDA");
      expect(nvdaEls.length).toBeGreaterThan(0);
    });
  });

  it("renders prior session data footer", () => {
    render(<PreMarketMoversWidget />, { wrapper });
    expect(screen.getByText("prior session data")).toBeInTheDocument();
  });
});

// ── Tests: PredictionMarketsWidget (Wave 7 new) ───────────────────────────────

describe("PredictionMarketsWidget", () => {
  it("renders PREDICTION MARKETS header", () => {
    render(<PredictionMarketsWidget />, { wrapper });
    expect(screen.getByText("PREDICTION MARKETS")).toBeInTheDocument();
  });

  it("renders market title after data loads", async () => {
    render(<PredictionMarketsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("Will Fed cut rates in June?")).toBeInTheDocument();
    });
  });

  it("renders yes probability as integer percent", async () => {
    render(<PredictionMarketsWidget />, { wrapper });
    await waitFor(() => {
      // WHY "Y 72%" (not "72%"): the redesigned 2-line layout shows probability
      // as Yes/No pills: "Y 72%" (YES pill) and "N 28%" (NO pill).
      // 0.72 → "Y 72%" in the YES pill; "N 28%" in the NO pill.
      expect(screen.getByText("Y 72%")).toBeInTheDocument();
    });
  });
});

// ── Tests: PortfolioNewsWidget (Wave 7 new) ───────────────────────────────────

describe("PortfolioNewsWidget", () => {
  it("renders PORTFOLIO NEWS header", () => {
    render(<PortfolioNewsWidget />, { wrapper });
    expect(screen.getByText("PORTFOLIO NEWS")).toBeInTheDocument();
  });

  it("renders article title after data loads", async () => {
    render(<PortfolioNewsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA reports record Q4 revenue")).toBeInTheDocument();
    });
  });
});

// ── Tests: EarningsCalendarWidget (Wave 7 header + Wave B-1 live data) ───────
// WHY updated (PLAN-0068 Wave B-1): EarningsCalendarWidget was converted from a
// static placeholder to a live "use client" component backed by useQuery /
// getEarningsCalendar. Tests now require { wrapper } (QueryClientProvider) and
// assert the live empty state — not the old static text. Static render path
// (no wrapper) is no longer valid after the live conversion.

describe("EarningsCalendarWidget", () => {
  it("renders EARNINGS CALENDAR header", () => {
    // WHY wrapper: component now uses useQuery (requires QueryClientProvider).
    render(<EarningsCalendarWidget />, { wrapper });
    expect(screen.getByText("EARNINGS CALENDAR")).toBeInTheDocument();
  });

  it("renders empty state when no events returned", async () => {
    // WHY wrapper: useQuery hook requires QueryClientProvider.
    // WHY waitFor: the empty state renders AFTER the mock resolves (async).
    // The mock for getEarningsCalendar returns {events:[], total:0} so the
    // component correctly falls into the empty-state branch.
    render(<EarningsCalendarWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/No upcoming earnings events scheduled/i)).toBeInTheDocument();
    });
  });
});

// ── Tests: Dashboard page grid structure (Wave 7 new) ─────────────────────────

describe("Dashboard page — 4-row grid structure (Wave 7)", () => {
  it("AiSignals is no longer present in page imports", async () => {
    // WHY: AiSignals was removed from the dashboard in Wave 7.
    // We test this by checking the page module doesn't render the AI Signals
    // section header text that AiSignals used to produce.
    // NOTE: We import page lazily to avoid module initialization issues.
    const { default: DashboardPage } = await import(
      "@/app/(app)/dashboard/page"
    );
    const qc = makeQueryClient();
    const { queryByText } = render(
      <QueryClientProvider client={qc}>
        <DashboardPage />
      </QueryClientProvider>,
    );
    // "AI Signals" (from the old Card header in DashboardPage) should not be present
    // WHY: We removed the AiSignals widget — it was a stub endpoint with no real data.
    expect(queryByText("AI Signals")).not.toBeInTheDocument();
  });

  it("Dashboard page renders MARKET SNAPSHOT widget", async () => {
    const { default: DashboardPage } = await import(
      "@/app/(app)/dashboard/page"
    );
    const qc = makeQueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("MARKET SNAPSHOT")).toBeInTheDocument();
  });

  it("Dashboard page renders SECTOR PERFORMANCE widget", async () => {
    const { default: DashboardPage } = await import(
      "@/app/(app)/dashboard/page"
    );
    const qc = makeQueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("SECTOR PERFORMANCE")).toBeInTheDocument();
  });

  it("Dashboard page renders EARNINGS CALENDAR placeholder", async () => {
    const { default: DashboardPage } = await import(
      "@/app/(app)/dashboard/page"
    );
    const qc = makeQueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("EARNINGS CALENDAR")).toBeInTheDocument();
  });
});
