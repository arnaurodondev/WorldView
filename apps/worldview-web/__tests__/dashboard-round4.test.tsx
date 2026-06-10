/**
 * __tests__/dashboard-round4.test.tsx — Round-4 dashboard hardening tests
 *
 * WHY THIS EXISTS: Round 4 (hardening sprint, 2026-06-10) closed three gaps:
 *   1. Error recovery — every widget now renders a NAMED error state with a
 *      Retry action wired to the failing query's refetch(). Pre-Round-4,
 *      several widgets either showed bespoke text with no recovery path
 *      (TopMovers, EconomicCalendar, RecentAlerts) or fell through to a
 *      MISLEADING empty state on fetch failure (PortfolioSummary rendered
 *      "No portfolio yet" when /v1/portfolios 500'd). These tests pin
 *      error → click Retry → queryFn called again → recovered render.
 *   2. Accessibility — role="region" + aria-label landmarks per widget,
 *      role="tablist" on the MoversWidgetTabs strip (its role="tab" children
 *      were orphaned), and the ▲/▼ direction glyphs that guarantee the
 *      usePriceFlash tint is never the ONLY change signal.
 *   3. Performance — MarketClock 1 Hz tick re-renders ONLY its own subtree
 *      (sibling isolation), and the Round-2 shared query keys have not
 *      drifted (PortfolioNewsWidget now shares qk.portfolios.list() with
 *      PortfolioSummary → exactly ONE getPortfolios call per page).
 *
 * Existing tests in dashboard.test.tsx / dashboard-round1/2/3 are untouched
 * (R19) — Round-4 kept every pinned empty-state string and error copy key.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import { SectorHeatmapWidget } from "@/components/dashboard/SectorHeatmapWidget";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";
import { MarketClockWidget } from "@/components/dashboard/MarketClockWidget";
import { MoversWidgetTabs } from "@/components/dashboard/MoversWidgetTabs";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
import { WatchlistQuickViewWidget } from "@/components/dashboard/WatchlistQuickViewWidget";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";

// ── Next.js router mock ───────────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── AlertStreamContext mock (RecentAlerts) ────────────────────────────────────
vi.mock("@/contexts/AlertStreamContext", () => ({
  useAlertStream: vi.fn(() => ({
    recentAlerts: [],
    unreadCount: 0,
    connectionStatus: "disconnected" as const,
    markAllRead: vi.fn(),
  })),
  AlertStreamProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// ── Gateway mock — EMPTY responses everywhere ─────────────────────────────────
// WHY empty by default: Round 4's primary surface is the error→retry path, so
// each test overrides the relevant fn with mockRejectedValueOnce and then
// (optionally) a resolved value to prove the Retry click recovers the panel.
const gatewayMocks = {
  getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
  getMarketHeatmap: vi.fn().mockResolvedValue({ sectors: [] }),
  getTopMovers: vi.fn().mockResolvedValue({ movers: [], type: "gainers" as const }),
  getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
  getMarketSparklines: vi.fn().mockResolvedValue({}),
  getEconomicCalendar: vi.fn().mockResolvedValue({ events: [], total: 0 }),
  getEarningsCalendar: vi.fn().mockResolvedValue({ events: [], total: 0 }),
  getTopNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  getPendingAlerts: vi.fn().mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 10 }),
  getPortfolios: vi.fn().mockResolvedValue([]),
  getHoldings: vi.fn().mockResolvedValue({ portfolio_id: "p1", holdings: [] }),
  getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
  getPortfolioPerformance: vi.fn().mockResolvedValue({ return_abs: 0, return_pct: 0 }),
  getWatchlists: vi.fn().mockResolvedValue([]),
  getWatchlistInsights: vi.fn().mockResolvedValue({ movers: [] }),
  getOHLCV: vi.fn().mockResolvedValue({ bars: [] }),
  resolveTickersBatch: vi.fn().mockImplementation((tickers: string[]) =>
    Promise.resolve(Object.fromEntries(tickers.map((t) => [t, null]))),
  ),
  getCompanyOverview: vi.fn().mockResolvedValue({ instrument: null, quote: null }),
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
  // WHY retry:false: TanStack's default (or even the app's retry:1) would
  // swallow the FIRST rejection and re-call the queryFn before isError flips,
  // making the "called exactly twice after one Retry click" assertions racy.
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  // Clear CALL HISTORY on every gateway mock — several widgets share gateway
  // fns across tests (e.g. SectorHeatmapWidget also calls getTopMovers for
  // its drill-down popovers), so toHaveBeenCalledTimes assertions would
  // otherwise count calls from earlier tests. mockClear keeps the
  // implementations; the lines below restore the default resolved values.
  Object.values(gatewayMocks).forEach((m) => m.mockClear());
  // Restore the default mock universe so per-test rejections never leak.
  gatewayMocks.getAiSignals.mockResolvedValue({ signals: [] });
  gatewayMocks.getMarketHeatmap.mockResolvedValue({ sectors: [] });
  gatewayMocks.getTopMovers.mockResolvedValue({ movers: [], type: "gainers" as const });
  gatewayMocks.getEconomicCalendar.mockResolvedValue({ events: [], total: 0 });
  gatewayMocks.getPendingAlerts.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 10 });
  gatewayMocks.getPortfolios.mockResolvedValue([]);
  gatewayMocks.getHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
  gatewayMocks.getTopNews.mockResolvedValue({ articles: [], total: 0 });
  gatewayMocks.resolveTickersBatch.mockImplementation((tickers: string[]) =>
    Promise.resolve(Object.fromEntries(tickers.map((t) => [t, null]))),
  );
  gatewayMocks.getPortfolios.mockClear();
  vi.useRealTimers();
});

// ── 1. Error recovery — named error state + Retry → refetch() ─────────────────

describe("Round 4 — error states carry a working Retry action", () => {
  it("AiSignalsWidget: error → Retry click → refetch recovers the signal list", async () => {
    gatewayMocks.getAiSignals
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        signals: [
          {
            signal_id: "sig-1",
            entity_id: "0190aaaa-bbbb-cccc-dddd-eeeeffff0001",
            ticker: "NVDA",
            label: "POSITIVE",
            score: 0.87,
            article_title: "NVDA beats",
            created_at: new Date().toISOString(),
          },
        ],
      });

    render(<AiSignalsWidget />, { wrapper });

    // Named error state (dashboard.signals-error) — not a blank pane.
    expect(await screen.findByText("Signals unavailable")).toBeInTheDocument();

    // Retry → second getAiSignals call → data renders.
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(gatewayMocks.getAiSignals).toHaveBeenCalledTimes(2);
  });

  it("SectorHeatmapWidget: error → Retry click → refetch recovers the treemap", async () => {
    gatewayMocks.getMarketHeatmap
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        sectors: [{ name: "Information Technology", change_pct: 1.25 }],
      });

    render(<SectorHeatmapWidget />, { wrapper });
    expect(await screen.findByText("Sector data unavailable")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    // The recovered payload renders the abbreviated tile label.
    expect(await screen.findByText("Tech")).toBeInTheDocument();
    expect(gatewayMocks.getMarketHeatmap).toHaveBeenCalledTimes(2);
  });

  it("MarketSnapshotWidget: ids-query error → named error state + truthful footer + Retry", async () => {
    gatewayMocks.resolveTickersBatch
      .mockRejectedValueOnce(new Error("boom"))
      // Recovery payload: all tickers unresolved (null) — rows render "—".
      .mockImplementationOnce((tickers: string[]) =>
        Promise.resolve(Object.fromEntries(tickers.map((t) => [t, null]))),
      );

    render(<MarketSnapshotWidget />, { wrapper });
    expect(await screen.findByText("Snapshot unavailable")).toBeInTheDocument();
    // The footer must NOT claim "instruments not yet ingested" on a FETCH
    // failure — that string misdiagnoses a network error as a data gap.
    expect(screen.queryByText("instruments not yet ingested")).not.toBeInTheDocument();
    expect(screen.getByText("snapshot feed error")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(gatewayMocks.resolveTickersBatch).toHaveBeenCalledTimes(2),
    );
    // Recovered: error state gone, ticker rows render again.
    expect(await screen.findByText("SPY")).toBeInTheDocument();
  });

  it("PortfolioSummary: a failed portfolios fetch shows the ERROR state (not the misleading 'No portfolio yet') and Retry recovers", async () => {
    gatewayMocks.getPortfolios
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce([]);

    render(<PortfolioSummary />, { wrapper });

    // Pre-Round-4 regression target: fetch failure fell through to the
    // cold-start empty state. Pin the split: error first…
    expect(await screen.findByText("Portfolio unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No portfolio yet")).not.toBeInTheDocument();

    // …then Retry resolves (empty list) and the TRUE empty state renders.
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No portfolio yet")).toBeInTheDocument();
    expect(gatewayMocks.getPortfolios).toHaveBeenCalledTimes(2);
  });

  it("WatchlistQuickViewWidget: a failed portfolios fetch shows the error state (not 'Track your top positions here')", async () => {
    gatewayMocks.getPortfolios.mockRejectedValueOnce(new Error("boom"));

    render(<WatchlistQuickViewWidget />, { wrapper });
    expect(await screen.findByText("Portfolio unavailable")).toBeInTheDocument();
    expect(
      screen.queryByText("Track your top positions here"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("TopMovers: error → Retry click → refetch recovers the mover rows", async () => {
    gatewayMocks.getTopMovers
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        movers: [
          {
            instrument_id: "ins-1",
            entity_id: "ins-1",
            ticker: "NVDA",
            name: "NVIDIA Corp",
            price: 850,
            change_pct: 5.2,
            volume: 1,
          },
        ],
        type: "gainers" as const,
      });

    render(<TopMovers />, { wrapper });
    expect(await screen.findByText("Movers unavailable")).toBeInTheDocument();
    // The old bespoke copy misdiagnosed failures as ingestion gaps — gone.
    expect(
      screen.queryByText(/data will appear when market data is ingested/i),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(gatewayMocks.getTopMovers).toHaveBeenCalledTimes(2);
  });

  it("EconomicCalendar: error → Retry click → refetch is wired", async () => {
    gatewayMocks.getEconomicCalendar
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ events: [], total: 0 });

    render(<EconomicCalendar />, { wrapper });
    expect(
      await screen.findByText("Economic calendar unavailable"),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    // Recovery lands on the (truthful) named empty state.
    expect(
      await screen.findByText("No upcoming economic events scheduled."),
    ).toBeInTheDocument();
    expect(gatewayMocks.getEconomicCalendar).toHaveBeenCalledTimes(2);
  });

  it("RecentAlerts: error → Retry click → refetch is wired", async () => {
    gatewayMocks.getPendingAlerts
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ alerts: [], total: 0, offset: 0, limit: 10 });

    render(<RecentAlerts />, { wrapper });
    // findByText also absorbs the useAboveFoldReady rAF×2 query deferral.
    expect(await screen.findByText("Alerts unavailable")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No recent alerts.")).toBeInTheDocument();
    expect(gatewayMocks.getPendingAlerts).toHaveBeenCalledTimes(2);
  });
});

// ── 2. Accessibility — landmarks, tablist, direction glyphs ───────────────────

describe("Round 4 — widget region landmarks and ARIA structure", () => {
  it("MarketClockWidget exposes a named region landmark", () => {
    render(<MarketClockWidget />, { wrapper });
    expect(screen.getByRole("region", { name: "Market clock" })).toBeInTheDocument();
  });

  it("MarketSnapshotWidget exposes a named region landmark", async () => {
    render(<MarketSnapshotWidget />, { wrapper });
    expect(
      screen.getByRole("region", { name: "Market snapshot" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(gatewayMocks.resolveTickersBatch).toHaveBeenCalled(),
    );
  });

  it("PortfolioSummary keeps its region landmark across loading → empty states", async () => {
    // Never-settling promise pins the LOADING branch — the landmark must
    // already exist there (SR users can target the panel from first paint).
    gatewayMocks.getPortfolios.mockReturnValueOnce(new Promise(() => {}));
    const { unmount } = render(<PortfolioSummary />, { wrapper });
    expect(
      screen.getByRole("region", { name: "Portfolio summary" }),
    ).toBeInTheDocument();
    unmount();

    // Empty state branch carries the same landmark.
    render(<PortfolioSummary />, { wrapper });
    expect(await screen.findByText("No portfolio yet")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Portfolio summary" }),
    ).toBeInTheDocument();
  });

  it("MoversWidgetTabs wraps its role=tab buttons in a named tablist", () => {
    render(<MoversWidgetTabs />, { wrapper });
    const tablist = screen.getByRole("tablist", { name: "Movers source" });
    expect(tablist).toBeInTheDocument();
    // The three source tabs are owned by the tablist (no orphaned role=tab).
    const tabs = screen.getAllByRole("tab", { name: /MARKET|HOLDINGS|WATCHLIST/ });
    expect(tabs).toHaveLength(3);
    tabs.forEach((tab) => expect(tablist.contains(tab)).toBe(true));
  });

  it("MarketSnapshot rows carry the ▲ direction glyph — the price-flash tint is never the only signal", async () => {
    // Resolve one ticker and give it a positive quote so a data row renders.
    gatewayMocks.resolveTickersBatch.mockImplementation((tickers: string[]) =>
      Promise.resolve(
        Object.fromEntries(tickers.map((t) => [t, t === "SPY" ? "ins-spy" : null])),
      ),
    );
    gatewayMocks.getCompanyOverview.mockResolvedValue({
      instrument: { ticker: "SPY" },
      quote: { price: 512.34, change: 4.2, change_pct: 0.83 },
    });

    render(<MarketSnapshotWidget />, { wrapper });
    // The ▲ glyph + signed % is the persistent direction signal (WCAG: the
    // transient usePriceFlash tint is redundant, not load-bearing).
    expect(await screen.findByText(/▲ \+0\.83%/)).toBeInTheDocument();
  });
});

// ── 3. Performance — memo isolation + shared query keys ───────────────────────

describe("Round 4 — MarketClock tick isolation", () => {
  it("a 1 Hz clock tick re-renders only the clock subtree, never siblings", () => {
    vi.useFakeTimers();

    // Sibling spy — counts its own renders. It sits NEXT TO the clock under
    // a stateless parent (exactly the dashboard page topology: server-
    // component page, independent client widgets). If the clock's interval
    // state leaked upward (e.g. via a lifted context), this counter would
    // increment on every tick.
    let siblingRenders = 0;
    function SiblingSpy() {
      siblingRenders += 1;
      return <div data-testid="sibling" />;
    }
    function StatelessParent() {
      return (
        <div>
          <MarketClockWidget />
          <SiblingSpy />
        </div>
      );
    }

    render(<StatelessParent />, { wrapper });
    expect(siblingRenders).toBe(1);

    // Advance 5 ticks — the clock re-renders itself 5 times (its own
    // useState), the sibling must not re-render at all.
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(siblingRenders).toBe(1);

    vi.useRealTimers();
  });
});

describe("Round 4 — shared query keys do not duplicate fetches", () => {
  it("PortfolioSummary + PortfolioNewsWidget share qk.portfolios.list() → ONE getPortfolios call", async () => {
    // Round-4 fix under test: PortfolioNewsWidget previously used the private
    // ["dashboard-portfolio-news-portfolios"] key — a second /v1/portfolios
    // round-trip for byte-identical data on every dashboard load.
    render(
      <>
        <PortfolioSummary />
        <PortfolioNewsWidget />
      </>,
      { wrapper },
    );

    // Wait for BOTH widgets to settle (news widget defers one paint via
    // useAboveFoldReady, then reads the already-cached portfolios entry).
    expect(await screen.findByText("No portfolio yet")).toBeInTheDocument();
    expect(await screen.findByText("No recent news")).toBeInTheDocument();

    await waitFor(() => {
      expect(gatewayMocks.getPortfolios).toHaveBeenCalledTimes(1);
    });
  });
});
