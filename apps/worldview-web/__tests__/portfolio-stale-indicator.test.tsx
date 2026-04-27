/**
 * __tests__/portfolio-stale-indicator.test.tsx — Tests for W2-9: PortfolioSummary
 * stale/delayed quote indicator ("~" prefix on total value and P&L)
 *
 * WHY THIS EXISTS: PortfolioSummary now shows a "~" prefix on the total portfolio
 * value and unrealised P&L when any holding has a delayed/stale/unavailable quote,
 * or when a quote is missing entirely. These tests verify the three rendering paths:
 *
 *   1. All quotes live/recent → no "~" prefix anywhere
 *   2. At least one quote is delayed → "~" appears on total value and P&L
 *   3. A holding has no quote (missing from batch response) → "~" appears
 *
 * WHY MOCK gateway: deterministic quote freshness_status values; no network.
 * WHY MOCK useAuth: eliminates AuthContext tree dependency for isolation.
 *
 * DATA SOURCE: Mocked gateway client
 * DESIGN REFERENCE: PLAN-0036 W2-9 — PortfolioSummary stale indicator
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: PortfolioSummary renders a <Link href="/portfolio"> which requires
// the Next.js router context. We stub it to a no-op so the component mounts.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY: PortfolioSummary calls useAuth() to gate queries on accessToken.
// We always return a valid token so the three useQuery calls actually fire.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ───────────────────────────────────────────────────────────────
// WHY mock each method individually: lets each test configure a minimal fixture
// without repeating unrelated method stubs.
const mockGetPortfolios = vi.fn();
const mockGetHoldings = vi.fn();
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPortfolios: mockGetPortfolios,
    getHoldings: mockGetHoldings,
    getBatchQuotes: mockGetBatchQuotes,
    // Auth plumbing expected by useAuth under the hood
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Fixtures ───────────────────────────────────────────────────────────────────

const PORTFOLIO = {
  portfolio_id: "port-1",
  name: "Test Portfolio",
  currency: "USD",
  owner_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// One holding: 10 shares of AAPL at average cost $150
const HOLDINGS = {
  portfolio_id: "port-1",
  holdings: [
    {
      holding_id: "h-1",
      portfolio_id: "port-1",
      instrument_id: "aapl-id",
      entity_id: "aapl-entity",
      ticker: "AAPL",
      name: "Apple Inc.",
      quantity: 10,
      average_cost: 150,
      current_price: null,
      unrealised_pnl: null,
      unrealised_pnl_pct: null,
      portfolio_weight: null,
    },
  ],
  total_value: null,
  total_cost: null,
  total_unrealised_pnl: null,
  total_unrealised_pnl_pct: null,
};

// Live quote — freshness_status = "live"
const LIVE_QUOTE = {
  instrument_id: "aapl-id",
  ticker: "AAPL",
  price: 180,
  change: 2,
  change_pct: 1.12,
  timestamp: "2026-04-24T14:00:00Z",
  volume: 50_000_000,
  freshness_status: "live" as const,
  source: "fresh_quote" as const,
  data_as_of: "2026-04-24T14:00:00Z",
  stale_reason: null,
};

// Delayed quote — freshness_status = "delayed"
const DELAYED_QUOTE = {
  ...LIVE_QUOTE,
  freshness_status: "delayed" as const,
  source: "bulk_quote" as const,
  stale_reason: "No quote in last 15 min",
};

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * makeQueryClient — fresh QueryClient per test to prevent state bleeding
 * WHY retry: false: avoids hanging tests from TanStack Query's retry delays
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

/**
 * makeWrapper — QueryClientProvider wrapper
 * WHY: TanStack Query hooks require a provider to be present in the tree
 */
function makeWrapper() {
  const qc = makeQueryClient();
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Import component AFTER mocks are established ──────────────────────────────
// WHY late import: vi.mock() hoisting requires mocks to be defined before the
// module under test is loaded into the test's module registry.
const { PortfolioSummary } = await import(
  "@/components/dashboard/PortfolioSummary"
);

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("PortfolioSummary — stale indicator (W2-9)", () => {
  beforeEach(() => {
    // Default: a portfolio with one holding
    mockGetPortfolios.mockResolvedValue([PORTFOLIO]);
    mockGetHoldings.mockResolvedValue(HOLDINGS);
  });

  it("does NOT show ~ prefix when all quotes are live", async () => {
    // WHY: live quotes mean the total value is accurate — no approximation caveat needed
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { "aapl-id": LIVE_QUOTE },
    });

    render(<PortfolioSummary />, { wrapper: makeWrapper() });

    // Wait for all three queries to resolve.
    // WHY getAllByText: $1,800.00 appears twice — once as the portfolio total (large <p>)
    // and once in the AAPL holding row value. getAllByText avoids the "multiple elements" error.
    await waitFor(() => {
      const allPrices = screen.getAllByText("$1,800.00");
      expect(allPrices.length).toBeGreaterThanOrEqual(1);
    });

    // WHY query for the tilde span specifically: the "~" is inside a <span> with
    // a title attribute — the closest selector that won't false-positive on other content
    const tildeSpan = screen.queryByTitle("Some prices are delayed or unavailable");
    expect(tildeSpan).not.toBeInTheDocument();

    // WHY also check the explanatory note: if "~" is absent, the note should be too
    expect(screen.queryByText("Some prices are delayed")).not.toBeInTheDocument();
  });

  it("shows ~ prefix on total value and P&L when a quote is delayed", async () => {
    // WHY delayed: freshness_status = "delayed" means the price is older than 15 min.
    // The portfolio total derived from it is approximate.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { "aapl-id": DELAYED_QUOTE },
    });

    render(<PortfolioSummary />, { wrapper: makeWrapper() });

    // Wait for the total value to render.
    // WHY getAllByText: $1,800.00 appears twice (portfolio total + holding row).
    await waitFor(() => {
      expect(screen.getAllByText("$1,800.00").length).toBeGreaterThanOrEqual(1);
    });

    // WHY queryByTitle: the tilde span has a descriptive title attribute.
    // This is the canonical way to find it without coupling to DOM position.
    const tildeSpan = screen.getByTitle("Some prices are delayed or unavailable");
    expect(tildeSpan).toBeInTheDocument();
    expect(tildeSpan).toHaveTextContent("~");

    // WHY also check the note: both the "~" and the note should appear together
    expect(screen.getByText("Some prices are delayed")).toBeInTheDocument();
  });

  it("shows ~ prefix when a holding has no quote at all (missing from response)", async () => {
    // WHY empty quotes: getBatchQuotes may return fewer results than requested
    // if a symbol is not found in S3. The holding falls back to average_cost.
    mockGetBatchQuotes.mockResolvedValue({
      quotes: {}, // aapl-id is missing — no price for this holding
    });

    render(<PortfolioSummary />, { wrapper: makeWrapper() });

    // Wait for the total value to render (uses average_cost = $150 as fallback).
    // WHY getAllByText: $1,500.00 appears in both the total and the holding row.
    await waitFor(() => {
      expect(screen.getAllByText("$1,500.00").length).toBeGreaterThanOrEqual(1);
    });

    // Missing quote → isApproximate = true → "~" should appear
    const tildeSpan = screen.getByTitle("Some prices are delayed or unavailable");
    expect(tildeSpan).toBeInTheDocument();
    expect(tildeSpan).toHaveTextContent("~");

    expect(screen.getByText("Some prices are delayed")).toBeInTheDocument();
  });

  it("shows ~ prefix when freshness_status is 'stale'", async () => {
    // WHY stale: freshness_status = "stale" means the price is > 1 day old.
    // Even more reason to show the approximation caveat.
    const staleQuote = {
      ...LIVE_QUOTE,
      freshness_status: "stale" as const,
      stale_reason: "No data for >1 day",
    };
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { "aapl-id": staleQuote },
    });

    render(<PortfolioSummary />, { wrapper: makeWrapper() });

    // WHY getAllByText: $1,800.00 appears in both the total and the holding row.
    await waitFor(() => {
      expect(screen.getAllByText("$1,800.00").length).toBeGreaterThanOrEqual(1);
    });

    expect(
      screen.getByTitle("Some prices are delayed or unavailable"),
    ).toBeInTheDocument();
  });

  it("does NOT show ~ when freshness_status is 'recent'", async () => {
    // WHY recent: "recent" means the price is < 5 min old — fresh enough to trust.
    // No caveat needed.
    const recentQuote = {
      ...LIVE_QUOTE,
      freshness_status: "recent" as const,
    };
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { "aapl-id": recentQuote },
    });

    render(<PortfolioSummary />, { wrapper: makeWrapper() });

    // WHY getAllByText: $1,800.00 appears in both the total and the holding row.
    await waitFor(() => {
      expect(screen.getAllByText("$1,800.00").length).toBeGreaterThanOrEqual(1);
    });

    expect(
      screen.queryByTitle("Some prices are delayed or unavailable"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Some prices are delayed")).not.toBeInTheDocument();
  });
});
