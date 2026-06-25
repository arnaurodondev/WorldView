/**
 * __tests__/dashboard-round3.test.tsx — Round-3 dashboard polish tests
 *
 * WHY THIS EXISTS: Round 3 (polish sprint, 2026-06-10) changed three classes
 * of dashboard behaviour that need pinning:
 *   1. Empty-state migration — every widget's panel-level empty state now
 *      renders through the shared components/primitives/EmptyState with a
 *      named `dashboard.*` copy key (DESIGN_SYSTEM §15.12). These tests pin
 *      the rendered copy and the role="status" announcement.
 *   2. Shape-matched skeletons — loading states mirror the loaded layout
 *      (row heights + column slots). We pin skeleton presence + row geometry
 *      via the [data-slot="skeleton"] convention.
 *   3. usePriceFlash — the index strip's transient price-tick tint (item 6):
 *      discrete state (no keyframes, NFR-6), cleared after PRICE_FLASH_MS,
 *      disabled under prefers-reduced-motion.
 *
 * Existing tests in dashboard.test.tsx / dashboard-round1/2 are untouched
 * (R19) — copy keys were chosen so their pinned strings keep resolving.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AiSignalsWidget } from "@/components/dashboard/AiSignalsWidget";
import { PredictionMarketsWidget } from "@/components/dashboard/PredictionMarketsWidget";
import { EconomicCalendar } from "@/components/dashboard/EconomicCalendar";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";
import { PortfolioSummary } from "@/components/dashboard/PortfolioSummary";
import { RecentAlerts } from "@/components/dashboard/RecentAlerts";
import { TopMovers } from "@/components/dashboard/TopMovers";
import { MarketSnapshotWidget } from "@/components/dashboard/MarketSnapshotWidget";
import { usePriceFlash, PRICE_FLASH_MS } from "@/features/dashboard/hooks/usePriceFlash";

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
// WHY empty by default: Round 3's primary new surface is the named empty
// state per widget, so the default mock universe is "authenticated user,
// zero data" — each describe block then opts into data where needed via
// the mutable holder below.
const gatewayMocks = {
  getAiSignals: vi.fn().mockResolvedValue({ signals: [] }),
  getPredictionMarkets: vi.fn().mockResolvedValue({ markets: [], total: 0 }),
  getPredictionMarketCategories: vi.fn().mockResolvedValue({ total: 0, items: [] }),
  getPredictionMarketHistory: vi.fn().mockResolvedValue({ points: [] }),
  getEconomicCalendar: vi.fn().mockResolvedValue({ events: [], total: 0 }),
  getEarningsCalendar: vi.fn().mockResolvedValue({ events: [], total: 0 }),
  getTopNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  // W4 fix: PortfolioNewsWidget fans out per-holding entity news. Default empty
  // articles; the no-news test overrides holdings/portfolio per-test so its
  // empty-state reads "no news" (holding present) not "no positions".
  getEntityNews: vi.fn().mockResolvedValue({ articles: [], total: 0 }),
  getPendingAlerts: vi.fn().mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 10 }),
  getPortfolios: vi.fn().mockResolvedValue([]),
  getHoldings: vi.fn().mockResolvedValue({ portfolio_id: "p1", holdings: [] }),
  getTopMovers: vi.fn().mockResolvedValue({ movers: [], type: "gainers" as const }),
  getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
  getMarketSparklines: vi.fn().mockResolvedValue({}),
  getMarketHeatmap: vi.fn().mockResolvedValue({ sectors: [] }),
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
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  // Restore any per-test mockReturnValue overrides (never-resolving promises
  // used by the skeleton tests would otherwise leak into later tests).
  gatewayMocks.getPredictionMarkets.mockResolvedValue({ markets: [], total: 0 });
  gatewayMocks.getAiSignals.mockResolvedValue({ signals: [] });
  gatewayMocks.getPendingAlerts.mockResolvedValue({ alerts: [], total: 0, offset: 0, limit: 10 });
  // Drop any matchMedia stub installed by the reduced-motion test.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).matchMedia;
});

// ── 1. Empty-state migration (item 4) ─────────────────────────────────────────

describe("Round 3 — named empty states via shared EmptyState primitive", () => {
  it("AiSignalsWidget renders the dashboard.no-signals copy with role=status", async () => {
    // 2026-06-12 Wave-4 pivot: the widget is now a NEWS MOMENTUM feed, so the
    // dashboard.no-signals copy was retargeted (title/body) — still rendered
    // through the shared EmptyState primitive with role=status.
    render(<AiSignalsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No news momentum yet")).toBeInTheDocument();
    });
    expect(screen.getByText(/Top news stories appear here/i)).toBeInTheDocument();
    // The shared primitive announces itself for assistive tech.
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("PredictionMarketsWidget renders the dashboard.no-markets copy (no more 'data loading…' lie)", async () => {
    render(<PredictionMarketsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No open prediction markets")).toBeInTheDocument();
    });
    // The old copy claimed the data was still loading even after the query
    // settled with zero rows — pin its removal.
    expect(screen.queryByText(/Prediction market data loading/i)).not.toBeInTheDocument();
  });

  it("EconomicCalendar keeps its exact pre-migration copy through the registry", async () => {
    render(<EconomicCalendar />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText("No upcoming economic events scheduled."),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Economic events populate as market calendar data/i),
    ).toBeInTheDocument();
  });

  it("PortfolioNewsWidget renders dashboard.no-news when the feed is empty", async () => {
    // W4 fix: the widget now scopes news per-holding. "No recent news" is the
    // empty state when the user HAS holdings but those holdings have no news —
    // distinct from "no positions". So this test overrides the portfolio +
    // holdings (a single NVDA holding) while keeping getEntityNews empty.
    // afterEach restores the empty defaults (so the no-portfolio test below
    // still sees []), and we restore them here too for belt-and-braces.
    gatewayMocks.getPortfolios.mockResolvedValue([
      {
        portfolio_id: "p1",
        name: "Test",
        currency: "USD",
        owner_id: "u1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);
    gatewayMocks.getHoldings.mockResolvedValue({
      portfolio_id: "p1",
      holdings: [
        {
          holding_id: "h-nvda",
          portfolio_id: "p1",
          instrument_id: "ins-nvda",
          entity_id: "ent-nvda",
          ticker: "NVDA",
          name: "NVIDIA Corp",
          quantity: 10,
          average_cost: 700,
          current_price: 800,
          currency: "USD",
          asset_class: "equity",
        },
      ],
    });
    gatewayMocks.getEntityNews.mockResolvedValue({ articles: [], total: 0 });

    render(<PortfolioNewsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No recent news")).toBeInTheDocument();
    });

    // Restore empty defaults so later tests (no-portfolio) aren't polluted.
    gatewayMocks.getPortfolios.mockResolvedValue([]);
    gatewayMocks.getHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
  });

  it("PortfolioSummary renders dashboard.no-portfolio with a create-CTA link", async () => {
    render(<PortfolioSummary />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No portfolio yet")).toBeInTheDocument();
    });
    const cta = screen.getByRole("link", { name: /Create a portfolio/i });
    expect(cta).toHaveAttribute("href", "/portfolio");
  });

  it("RecentAlerts renders dashboard.no-alerts with an Alerts-page action link", async () => {
    render(<RecentAlerts />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No recent alerts.")).toBeInTheDocument();
    });
    const cta = screen.getByRole("link", { name: /Open Alerts page/i });
    expect(cta).toHaveAttribute("href", "/alerts");
  });

  it("TopMovers renders dashboard.no-movers when a side has zero rows", async () => {
    render(<TopMovers />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("No movers")).toBeInTheDocument();
    });
  });
});

// ── 2. Shape-matched skeletons (item 3) ───────────────────────────────────────

describe("Round 3 — shape-matched loading skeletons", () => {
  it("PredictionMarketsWidget skeleton renders 3 two-row market blocks (9 bars)", () => {
    // Never-settling promise keeps isLoading=true for the whole test.
    gatewayMocks.getPredictionMarkets.mockReturnValue(new Promise(() => {}));
    const { container } = render(<PredictionMarketsWidget />, { wrapper });
    // 3 markets × (title + chip + 2 pills + volume) = 3 × 5 skeleton bars —
    // the LOADED layout is 2 rows per market, so the skeleton must be too.
    const bars = container.querySelectorAll('[data-slot="skeleton"]');
    expect(bars.length).toBe(15);
  });

  it("MarketSnapshotWidget skeleton includes the two group-label slots and 11 four-cell rows", () => {
    gatewayMocks.resolveTickersBatch.mockReturnValue(new Promise(() => {}));
    const { container } = render(<MarketSnapshotWidget />, { wrapper });
    // 2 group labels + 11 rows × 4 column cells = 46 placeholders.
    const bars = container.querySelectorAll('[data-slot="skeleton"]');
    expect(bars.length).toBe(2 + 11 * 4);
    // Restore for later tests (this mock is module-scoped).
    gatewayMocks.resolveTickersBatch.mockImplementation((tickers: string[]) =>
      Promise.resolve(Object.fromEntries(tickers.map((t) => [t, null]))),
    );
  });

  it("RecentAlerts skeleton uses 22px terminal rows (matches the loaded row height)", async () => {
    gatewayMocks.getPendingAlerts.mockReturnValue(new Promise(() => {}));
    const { container } = render(<RecentAlerts />, { wrapper });
    // WHY waitFor: RecentAlerts defers its REST poll behind useAboveFoldReady
    // (F-4 socket-priority gating) — the query only starts (and isLoading
    // only becomes true) one paint after mount.
    await waitFor(() => {
      const bars = container.querySelectorAll('[data-slot="skeleton"]');
      expect(bars.length).toBe(5 * 3);
    });
    // Every skeleton row is h-[22px] — the loaded alert rows' exact height.
    const firstRow = container.querySelector('[data-slot="skeleton"]')!.parentElement!;
    expect(firstRow.className).toContain("h-[22px]");
  });
});

// ── 3. Hover / focus affordances (item 5) ─────────────────────────────────────

describe("Round 3 — keyboard focus rings on interactive elements", () => {
  it("TopMovers rows carry a focus-visible ring class", async () => {
    gatewayMocks.getTopMovers.mockResolvedValue({
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
    const row = await screen.findByRole("button", {
      name: "Navigate to NVDA instrument page",
    });
    expect(row.className).toContain("focus-visible:ring-ring");
    expect(row.className).toContain("hover:bg-muted/30");
    // Restore the empty default for other tests.
    gatewayMocks.getTopMovers.mockResolvedValue({ movers: [], type: "gainers" as const });
  });
});

// ── 4. Semantic color tokens (item 2) ─────────────────────────────────────────

describe("Round 3 — §15.11 semantic token consumption in news momentum", () => {
  it("positive news renders the text-positive sentiment dot (not hsl-var arbitrary classes)", async () => {
    // 2026-06-12 Wave-4 pivot: the widget now renders a NEWS MOMENTUM feed, so
    // the semantic-token check moves from the old score bar to the sentiment dot.
    gatewayMocks.getAiSignals.mockResolvedValue({
      signals: [
        {
          entity_id: "e-1",
          ticker: "NVDA",
          name: "Nvidia",
          count: 6,
          prior_count: 2,
          delta: 4,
          delta_pct: 200,
          top_article: {
            id: "art-1",
            title: "NVDA beats",
            url: "https://example.com/nvda",
            source: "example",
            sentiment: "positive",
            relevance: 0.87,
            published_at: new Date().toISOString(),
          },
        },
      ],
      window_hours: 24,
    });
    const { container } = render(<AiSignalsWidget />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("NVDA beats")).toBeInTheDocument();
    });
    // The trend label + sentiment dot use the semantic utility…
    expect(container.querySelector(".text-positive")).not.toBeNull();
    // …and never the arbitrary-value spelling §15.11 reserves for canvas/SVG.
    expect(container.innerHTML).not.toContain("text-[hsl(var(--positive))]");
    expect(container.innerHTML).not.toContain("bg-[hsl(var(--positive))]");
  });
});

// ── 5. usePriceFlash (item 6) ─────────────────────────────────────────────────

describe("Round 3 — usePriceFlash transient tick indicator", () => {
  it("returns null on first render and after a null→number 'load' transition", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ v }: { v: number | null }) => usePriceFlash(v),
      { initialProps: { v: null as number | null } },
    );
    expect(result.current).toBeNull();
    // First data arrival is a LOAD, not a tick — must not flash.
    rerender({ v: 100 });
    expect(result.current).toBeNull();
    vi.useRealTimers();
  });

  it("flashes 'up' on an increase and clears after PRICE_FLASH_MS", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ v }: { v: number | null }) => usePriceFlash(v),
      { initialProps: { v: 100 as number | null } },
    );
    rerender({ v: 101.5 });
    expect(result.current).toBe("up");
    act(() => {
      vi.advanceTimersByTime(PRICE_FLASH_MS + 1);
    });
    expect(result.current).toBeNull();
    vi.useRealTimers();
  });

  it("flashes 'down' on a decrease", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ v }: { v: number | null }) => usePriceFlash(v),
      { initialProps: { v: 100 as number | null } },
    );
    rerender({ v: 99.25 });
    expect(result.current).toBe("down");
    vi.useRealTimers();
  });

  it("does not flash when the value is unchanged", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ v }: { v: number | null }) => usePriceFlash(v),
      { initialProps: { v: 100 as number | null } },
    );
    rerender({ v: 100 });
    expect(result.current).toBeNull();
    vi.useRealTimers();
  });

  it("stays silent under prefers-reduced-motion", () => {
    vi.useFakeTimers();
    // Stub the OS-level setting to "reduce" — the hook must never flash.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).matchMedia = vi.fn().mockReturnValue({ matches: true });
    const { result, rerender } = renderHook(
      ({ v }: { v: number | null }) => usePriceFlash(v),
      { initialProps: { v: 100 as number | null } },
    );
    rerender({ v: 105 });
    expect(result.current).toBeNull();
    vi.useRealTimers();
  });
});
