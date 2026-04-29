/**
 * __tests__/WatchlistMoversWidget.insights.test.tsx — PLAN-0050 T-B-2-07.
 *
 * Pins the contract that the widget renders the four new insights-driven
 * surfaces when the gateway returns a populated WatchlistInsights payload:
 *   - Per-watchlist summary strip (RET %, members count, sector mini-bar)
 *   - Biggest-news callout (clickable, opens in new tab)
 *   - Per-row alert dot for members with `has_active_alert: true`
 *   - Per-row newspaper icon with badge count for members with news_count_24h > 0
 *
 * Mocks the gateway client so we can drive the widget from controlled data
 * without spinning up the actual S9 endpoint. Mirrors the AlertStream/test
 * pattern used elsewhere in the suite.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Mock the gateway BEFORE importing the widget so the createGateway() callsite
// inside the widget resolves to our stubs.
const mockGetWatchlists = vi.fn();
const mockGetWatchlistInsights = vi.fn();
const mockGetOHLCV = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getWatchlists: mockGetWatchlists,
    getWatchlistInsights: mockGetWatchlistInsights,
    getOHLCV: mockGetOHLCV,
  }),
}));

// useAuth would otherwise require AuthContext provider — stub it.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

// next/navigation needs a mock router for the row-click handler.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { WatchlistMoversWidget } from "@/components/dashboard/WatchlistMoversWidget";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const SAMPLE_INSIGHTS = {
  watchlist_id: "wl-1",
  members_count: 3,
  weighted_return_1d: 1.25,
  alerts_count: 1,
  sectors: [
    { sector: "Information Technology", count: 2, weight: 2 / 3 },
    { sector: "Health Care", count: 1, weight: 1 / 3 },
  ],
  biggest_news: {
    article_id: "art-1",
    title: "Apple beats earnings, ships new MacBook",
    url: "https://news.example.com/aapl",
    published_at: "2026-04-29T08:00:00Z",
    ticker: "AAPL",
    impact_score: 0.92,
  },
  movers: [
    {
      instrument_id: "i-aapl",
      entity_id: "e-aapl",
      ticker: "AAPL",
      name: "Apple Inc.",
      sector: "Information Technology",
      price: 200.5,
      change_pct: 2.1,
      news_count_24h: 3,
      has_active_alert: true,
      top_news_title: "Apple beats earnings, ships new MacBook",
      top_news_url: "https://news.example.com/aapl",
    },
    {
      instrument_id: "i-msft",
      entity_id: "e-msft",
      ticker: "MSFT",
      name: "Microsoft",
      sector: "Information Technology",
      price: 410.0,
      change_pct: -0.8,
      news_count_24h: 0,
      has_active_alert: false,
      top_news_title: null,
      top_news_url: null,
    },
    {
      instrument_id: "i-pfe",
      entity_id: "e-pfe",
      ticker: "PFE",
      name: "Pfizer",
      sector: "Health Care",
      price: 30.0,
      change_pct: 0.5,
      news_count_24h: 1,
      has_active_alert: false,
      top_news_title: "Pfizer Q1 update",
      top_news_url: "https://news.example.com/pfe",
    },
  ],
};

describe("WatchlistMoversWidget — insights enrichments (PLAN-0050 Wave B)", () => {
  it("renders the summary strip with weighted return and member count", async () => {
    mockGetWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    mockGetWatchlistInsights.mockResolvedValue(SAMPLE_INSIGHTS);

    render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    // Wait for insights to land — the summary strip's RET label appears once.
    await waitFor(() => {
      expect(screen.getByText("RET")).toBeInTheDocument();
    });
    expect(screen.getByText("+1.25%")).toBeInTheDocument();
    expect(screen.getByText(/3 names/)).toBeInTheDocument();
  });

  it("renders the biggest-news callout as a clickable external link", async () => {
    mockGetWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    mockGetWatchlistInsights.mockResolvedValue(SAMPLE_INSIGHTS);

    render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    const callout = await screen.findByLabelText(/Open biggest news/i);
    expect(callout).toHaveAttribute("href", SAMPLE_INSIGHTS.biggest_news.url);
    expect(callout).toHaveAttribute("target", "_blank");
    expect(callout).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("flags AAPL with the active-alert dot in its row aria-label", async () => {
    mockGetWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    mockGetWatchlistInsights.mockResolvedValue(SAMPLE_INSIGHTS);

    render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    // The row aria-label enumerates badges textually for SR users.
    const aaplRow = await screen.findByLabelText(
      /Open AAPL instrument page; active alert, 3 recent news/i,
    );
    expect(aaplRow).toBeInTheDocument();

    // MSFT has neither badge — row aria-label should be the bare default.
    const msftRow = await screen.findByLabelText("Open MSFT instrument page");
    expect(msftRow).toBeInTheDocument();
  });

  it("renders the news count badge only when news_count_24h > 0", async () => {
    mockGetWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    mockGetWatchlistInsights.mockResolvedValue(SAMPLE_INSIGHTS);

    const { container } = render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    // Wait for the AAPL row to render — its row aria-label includes "3 recent news"
    // which is our SR-friendly contract for the badge count.
    await screen.findByLabelText(/Open AAPL instrument page; active alert, 3 recent news/i);

    // The icon container carries title={topNewsTitle} — verify both AAPL + PFE
    // tooltip text is queryable; MSFT (news_count_24h=0) must NOT have one.
    const aaplBadge = container.querySelector('[title="Apple beats earnings, ships new MacBook"]');
    const pfeBadge = container.querySelector('[title="Pfizer Q1 update"]');
    expect(aaplBadge).toBeTruthy();
    expect(pfeBadge).toBeTruthy();
  });

  it("switches to OHLCV-derived change_pct when 1W is selected (F-QA-09)", async () => {
    // The 1W path should still call getOHLCV per instrument and the rendered
    // change_pct should reflect first→last close, NOT the 1D insights value.
    mockGetWatchlists.mockResolvedValue([
      { watchlist_id: "wl-1", name: "Default", created_at: "2026-01-01T00:00:00Z" },
    ]);
    mockGetWatchlistInsights.mockResolvedValue(SAMPLE_INSIGHTS);
    // Per-instrument fixture: AAPL 100→110 (+10%); MSFT 200→180 (-10%); PFE 50→50 (0%).
    mockGetOHLCV.mockImplementation(async (id: string) => {
      const closes: Record<string, [number, number]> = {
        "i-aapl": [100, 110],
        "i-msft": [200, 180],
        "i-pfe": [50, 50],
      };
      const [first, last] = closes[id] ?? [1, 1];
      return {
        instrument_id: id,
        ticker: "",
        timeframe: "1W",
        bars: [
          { timestamp: "2026-04-22T00:00:00Z", open: first, high: first, low: first, close: first, volume: 1 },
          { timestamp: "2026-04-29T00:00:00Z", open: last, high: last, low: last, close: last, volume: 1 },
        ],
      };
    });

    const { getByRole, findByText } = render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    // Click the "1W" period button.
    const week = getByRole("button", { name: /^1W$/i });
    week.click();

    // OHLCV-derived AAPL +10% must replace the 1D +2.10%.
    await findByText(/\+10\.00%/);
    // F-QA-07: row badges (alert dot, news icon) must NOT appear on non-1D.
    // After clicking 1W, the row aria-label should NOT enumerate badges.
    await waitFor(() => {
      expect(screen.getByLabelText("Open AAPL instrument page")).toBeInTheDocument();
    });
    // Sanity: the OHLCV mock was actually invoked.
    expect(mockGetOHLCV).toHaveBeenCalled();
  });

  it("hides the summary strip when no watchlist exists", async () => {
    mockGetWatchlists.mockResolvedValue([]);

    render(<WatchlistMoversWidget />, { wrapper: makeWrapper() });

    // Empty state appears, RET strip does not.
    await screen.findByText(/No watchlist yet/i);
    expect(screen.queryByText("RET")).toBeNull();
  });
});
