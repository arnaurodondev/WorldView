/**
 * components/watchlist/__tests__/WatchlistInsightsPanel.test.tsx
 *
 * WHY THIS EXISTS: WatchlistInsightsPanel has 4 distinct render paths
 * (loading / data / empty / error) that are pure presentation logic.
 * Unit tests here pin those paths so future refactors cannot accidentally
 * collapse "No insights yet" into "Insights unavailable" or break the
 * positive/negative colour classes.
 *
 * DATA SOURCE: Mocked createGateway() → getWatchlistInsights()
 * DESIGN REFERENCE: PLAN-0091 Wave B-2 spec.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WatchlistInsightsPanel } from "../WatchlistInsightsPanel";

// ── Mock navigation (not used by the component but required by the Next.js
//    "use client" boundary in some build paths) ────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock — always returns a valid access token so the query fires ────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "Test", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — getWatchlistInsights returns whatever insightsMock resolves ─
// WHY a standalone vi.fn(): we reassign its implementation per test (mockResolvedValue /
// mockRejectedValue) in beforeEach so each test gets an isolated response.
const insightsMock = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getWatchlistInsights: insightsMock,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Query client wrapper (retry=false avoids async retry noise in tests) ──────
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Minimal WatchlistInsights payload with 2 movers + 1 article. */
const baseInsights = {
  watchlist_id: "wl-1",
  members_count: 2,
  movers: [
    {
      instrument_id: "i-aapl",
      entity_id: "e-aapl",
      ticker: "AAPL",
      name: "Apple Inc.",
      sector: "Technology",
      price: 185.5,
      // change_pct=2.1 → top mover (largest absolute value)
      change_pct: 2.1,
      news_count_24h: 3,
      has_active_alert: false,
      top_news_title: null,
      top_news_url: null,
    },
    {
      instrument_id: "i-msft",
      entity_id: "e-msft",
      ticker: "MSFT",
      name: "Microsoft Corp.",
      sector: "Technology",
      price: 420.0,
      change_pct: -1.2,
      news_count_24h: 1,
      has_active_alert: false,
      top_news_title: null,
      top_news_url: null,
    },
  ],
  weighted_return_1d: 0.45,
  sectors: [{ sector: "Technology", count: 2, weight: 1.0 }],
  biggest_news: {
    article_id: "art-1",
    title: "Apple beats earnings estimates",
    url: "https://example.com/apple-earnings",
    published_at: "2026-05-22T08:00:00Z",
    ticker: "AAPL",
    impact_score: 0.85,
  },
  alerts_count: 0,
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("WatchlistInsightsPanel", () => {
  beforeEach(() => {
    // Reset the mock before each test so one test's response doesn't leak.
    insightsMock.mockReset();
  });

  it("renders loading state while the query is in-flight", () => {
    // WHY never-resolving promise: keeps the query in the "loading" state
    // long enough for the render assertion to run. If we used a resolved
    // promise the component would skip straight to the data state.
    insightsMock.mockImplementation(() => new Promise(() => {}));

    render(
      <WatchlistInsightsPanel watchlistId="wl-1" />,
      { wrapper: makeWrapper() },
    );

    // The loading skeleton is a STATIC aria-busy container (no animate-pulse —
    // banned by DESIGN_SYSTEM.md §6.2; Round-4 hardening swapped the pulsing
    // blob for three static shape-matched bars). aria-busy="true" is the
    // semantic loading marker, so it's the right selector: it asserts the
    // accessible behaviour (screen readers announce "busy") rather than a
    // presentation class.
    const skeleton = document.querySelector('[aria-busy="true"]');
    expect(skeleton).toBeInTheDocument();
    // Shape-matching (§6.2): the skeleton renders exactly 3 bars — one per
    // insight row — so hydration causes zero layout shift.
    expect(skeleton?.children).toHaveLength(3);
    // Data rows should not be visible during loading.
    expect(screen.queryByText("TOP MOVER")).not.toBeInTheDocument();
  });

  it("renders 3 insight rows when data is available", async () => {
    insightsMock.mockResolvedValue(baseInsights);

    render(
      <WatchlistInsightsPanel watchlistId="wl-1" />,
      { wrapper: makeWrapper() },
    );

    // Wait for the async query to settle.
    await waitFor(() => {
      expect(screen.getByText("TOP MOVER")).toBeInTheDocument();
    });

    // Row 1 — top mover label + value.
    expect(screen.getByText("TOP MOVER")).toBeInTheDocument();
    // AAPL has the larger absolute change_pct (2.1 vs -1.2).
    expect(screen.getByText(/AAPL.*\+2\.10%/)).toBeInTheDocument();

    // Row 2 — news headline (truncated to 28 chars).
    expect(screen.getByText("TOP NEWS")).toBeInTheDocument();
    // "Apple beats earnings estim…" (28 chars + ellipsis)
    const newsEl = screen.getByText(/Apple beats earnings estim/);
    expect(newsEl).toBeInTheDocument();
    // Full title exposed in title attribute for accessibility.
    expect(newsEl.getAttribute("title")).toBe("Apple beats earnings estimates");

    // Row 3 — weighted return.
    expect(screen.getByText("WGTD RET 1D")).toBeInTheDocument();
    expect(screen.getByText("+0.45%")).toBeInTheDocument();
  });

  it('renders "No insights yet" for an empty watchlist (members_count === 0)', async () => {
    insightsMock.mockResolvedValue({
      ...baseInsights,
      members_count: 0,
      movers: [],
      weighted_return_1d: null,
      biggest_news: null,
    });

    render(
      <WatchlistInsightsPanel watchlistId="wl-empty" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("No insights yet")).toBeInTheDocument();
    });

    // Data rows must NOT appear for an empty watchlist.
    expect(screen.queryByText("TOP MOVER")).not.toBeInTheDocument();
  });

  it('renders "Insights unavailable" when the query errors', async () => {
    // Simulate a 500-level gateway failure.
    insightsMock.mockRejectedValue(new Error("Internal Server Error"));

    render(
      <WatchlistInsightsPanel watchlistId="wl-error" />,
      { wrapper: makeWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Insights unavailable")).toBeInTheDocument();
    });

    // Neither data rows nor loading skeleton should be visible.
    // (skeleton = the aria-busy container; see the loading-state test above —
    // the static §6.2 skeleton no longer uses animate-pulse.)
    expect(screen.queryByText("TOP MOVER")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeInTheDocument();
  });
});
