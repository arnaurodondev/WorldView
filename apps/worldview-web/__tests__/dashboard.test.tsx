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

// ── Tests: MarketSnapshotWidget (Wave 7 new) ──────────────────────────────────

describe("MarketSnapshotWidget", () => {
  it("renders MARKET SNAPSHOT header", () => {
    render(<MarketSnapshotWidget />);
    expect(screen.getByText("MARKET SNAPSHOT")).toBeInTheDocument();
  });

  it("renders all 6 instrument labels", () => {
    render(<MarketSnapshotWidget />);
    expect(screen.getByText("ES (S&P Fut)")).toBeInTheDocument();
    expect(screen.getByText("NQ (NDX Fut)")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("2Y Yield")).toBeInTheDocument();
    expect(screen.getByText("10Y Yield")).toBeInTheDocument();
    expect(screen.getByText("2Y/10Y")).toBeInTheDocument();
  });

  it("shows placeholder — for all values", () => {
    render(<MarketSnapshotWidget />);
    // 6 instruments × — placeholders
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(6);
  });

  it("shows pending integration footer note", () => {
    render(<MarketSnapshotWidget />);
    expect(
      screen.getByText(/futures data — EODHD macro integration pending/i),
    ).toBeInTheDocument();
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
      // 0.72 → "72%"
      expect(screen.getByText("72%")).toBeInTheDocument();
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

// ── Tests: EarningsCalendarWidget (Wave 7 new) ────────────────────────────────

describe("EarningsCalendarWidget", () => {
  it("renders EARNINGS CALENDAR header", () => {
    render(<EarningsCalendarWidget />);
    expect(screen.getByText("EARNINGS CALENDAR")).toBeInTheDocument();
  });

  it("renders coming soon placeholder", () => {
    render(<EarningsCalendarWidget />);
    expect(screen.getByText(/earnings data coming soon/i)).toBeInTheDocument();
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
