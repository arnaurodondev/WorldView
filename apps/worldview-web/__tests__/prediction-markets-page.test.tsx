/**
 * __tests__/prediction-markets-page.test.tsx — Unit tests for /prediction-markets page
 *
 * WHY THIS EXISTS: The /prediction-markets page was created as a bug fix
 * (BP-383) then formally closed as part of PLAN-0068 Wave C-2. Tests ensure
 * the page's core UI states and client-side filtering work correctly.
 *
 * COVERAGE:
 *   (a) Skeleton renders while data is loading
 *   (b) Market rows render when data resolves
 *   (c) Category pill filters hide non-matching markets (client-side)
 *   (d) Text search filters by title
 *   (e) Error state renders on fetch failure
 *   (f) Empty state renders when no markets returned
 *
 * DATA SOURCE: Mocked gateway — no real S9 calls.
 * DESIGN REFERENCE: PLAN-0068 Wave C-2 spec.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PredictionMarketsPage from "@/app/(app)/prediction-markets/page";
import type { PredictionMarket } from "@/types/api";

// ── Next.js navigation mock ────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/prediction-markets"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ──────────────────────────────────────────────────────────────────

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

// ── Gateway mock ───────────────────────────────────────────────────────────────

const mockGetPredictionMarkets = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPredictionMarkets: mockGetPredictionMarkets,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Test data helpers ──────────────────────────────────────────────────────────

function makeMarket(overrides: Partial<PredictionMarket> = {}): PredictionMarket {
  return {
    market_id: `m-${Math.random().toString(36).slice(2)}`,
    title: "Will Fed raise rates in 2025?",
    description: "Prediction market on Fed rate decision.",
    yes_probability: 0.55,
    no_probability: 0.45,
    volume_usd: 50_000,
    status: "open",
    resolution_date: "2025-12-31T23:59:00Z",
    entity_ids: [],
    tickers: [],
    source: "polymarket",
    url: "https://polymarket.com/event/test",
    market_slug: "fed-rate-2025",
    category: "macro",
    updated_at: "2026-05-01T00:00:00Z",
    ...overrides,
  };
}

// ── Query client factory ───────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("PredictionMarketsPage", () => {
  beforeEach(() => {
    mockGetPredictionMarkets.mockReset();
  });

  // (a) Skeleton while loading

  it("renders skeleton rows while the query is pending", () => {
    // Never resolves — stays in loading state
    mockGetPredictionMarkets.mockReturnValue(new Promise(() => {}));
    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    // WHY bg-muted: the worldview Skeleton component renders <div class="rounded-[2px] bg-muted ...">
    // (no animate-pulse — Bloomberg style, see components/ui/skeleton.tsx).
    // 14 skeleton rows × 2 divs each = 28 elements; we only assert ≥1 to be resilient to count changes.
    const skeletons = document.querySelectorAll(".bg-muted");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  // (b) Market rows render

  it("renders market rows when data resolves", async () => {
    const markets = [
      makeMarket({ title: "Will Fed cut rates in 2025?", category: "macro" }),
      makeMarket({ title: "Will Trump win re-election?", category: "politics" }),
    ];
    mockGetPredictionMarkets.mockResolvedValue({ markets, total: 2 });

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Will Fed cut rates in 2025?")).toBeInTheDocument();
      expect(screen.getByText("Will Trump win re-election?")).toBeInTheDocument();
    });
  });

  it("shows the total count badge when data resolves", async () => {
    mockGetPredictionMarkets.mockResolvedValue({
      markets: [makeMarket()],
      total: 42,
    });

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("42 open")).toBeInTheDocument();
    });
  });

  // (c) Category pill filters

  it("hides markets that don't match the active category pill", async () => {
    const markets = [
      makeMarket({ title: "Fed rate decision", category: "macro" }),
      makeMarket({ title: "NBA Finals winner", category: "sports" }),
    ];
    mockGetPredictionMarkets.mockResolvedValue({ markets, total: 2 });

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Fed rate decision")).toBeInTheDocument();
    });

    // Click the "macro" category pill
    fireEvent.click(screen.getByRole("button", { name: /macro/i }));

    // macro market still visible
    expect(screen.getByText("Fed rate decision")).toBeInTheDocument();
    // sports market hidden
    expect(screen.queryByText("NBA Finals winner")).not.toBeInTheDocument();
  });

  it("shows all markets when the 'all' pill is active", async () => {
    const markets = [
      makeMarket({ title: "Fed rate decision", category: "macro" }),
      makeMarket({ title: "NBA Finals winner", category: "sports" }),
    ];
    mockGetPredictionMarkets.mockResolvedValue({ markets, total: 2 });

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Fed rate decision")).toBeInTheDocument();
    });

    // Filter to macro, then reset to all
    fireEvent.click(screen.getByRole("button", { name: /macro/i }));
    fireEvent.click(screen.getByRole("button", { name: /all/i }));

    expect(screen.getByText("Fed rate decision")).toBeInTheDocument();
    expect(screen.getByText("NBA Finals winner")).toBeInTheDocument();
  });

  // (d) Search filters

  it("filters by search term entered into the search input", async () => {
    const markets = [
      makeMarket({ title: "Fed rate decision 2025", category: "macro" }),
      makeMarket({ title: "NBA Finals winner", category: "sports" }),
    ];
    mockGetPredictionMarkets.mockResolvedValue({ markets, total: 2 });

    const user = userEvent.setup();
    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Fed rate decision 2025")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search markets/i);
    await user.type(searchInput, "nba");

    // NBA market visible, Fed market hidden
    expect(screen.getByText("NBA Finals winner")).toBeInTheDocument();
    expect(screen.queryByText("Fed rate decision 2025")).not.toBeInTheDocument();
  });

  it("shows 'no markets match' empty state when filters eliminate all results", async () => {
    const markets = [makeMarket({ title: "Fed rate decision", category: "macro" })];
    mockGetPredictionMarkets.mockResolvedValue({ markets, total: 1 });

    const user = userEvent.setup();
    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Fed rate decision")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/search markets/i);
    await user.type(searchInput, "xyzzy-no-match");

    expect(screen.getByText(/no markets match your filters/i)).toBeInTheDocument();
  });

  // (e) Error state

  it("renders error state when the query fails", async () => {
    mockGetPredictionMarkets.mockRejectedValue(new Error("Network error"));

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText(/failed to load prediction markets/i)).toBeInTheDocument();
    });
  });

  // (f) Empty state

  it("renders empty state when the API returns an empty markets list", async () => {
    mockGetPredictionMarkets.mockResolvedValue({ markets: [], total: 0 });

    render(<PredictionMarketsPage />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText(/no prediction markets available/i)).toBeInTheDocument();
    });
  });
});
