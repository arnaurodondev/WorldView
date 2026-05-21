/**
 * __tests__/portfolio.test.tsx — Unit tests for the Portfolio overview page
 *
 * WHY THIS FILE EXISTS: The portfolio page is the primary P&L view. Tests verify
 * that the W2 overview layout renders the expected content.
 *
 * W2 CHANGE: tabs are removed (PRD-0089 W2 §4.19). Holdings, transactions and
 * watchlists are now on separate routes. This file covers the /portfolio overview:
 *   - Holdings data renders
 *   - KPI strip renders with labels
 *   - AAPL and MSFT holding tickers appear in the table
 *   - RecentActivityStrip renders BUY/SELL transactions inline (no tab switch)
 *
 * WHY MOCK GATEWAY: We control exactly what data each query returns.
 * Without mocks, tests would depend on a live S9 instance and be flaky.
 *
 * DATA SOURCE: Mocked gateway client — controlled, deterministic
 * DESIGN REFERENCE: PRD-0028 §6.5 Portfolio, PRD-0089 W2 §4.19
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
// PLAN-0059 C-6: PortfolioPage reads URL state via nuqs (active period).
// The testing adapter provides a stub router so the hooks don't crash.
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PortfolioPage from "@/app/(app)/portfolio/page";

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: PortfolioPage calls useRouter().push() for hotkeys.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ────────────────────────────────────────────────────────────────
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

// ── Gateway mock ──────────────────────────────────────────────────────────────
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPortfolios: vi.fn().mockResolvedValue([
      {
        portfolio_id: "port-1",
        name: "My Portfolio",
        currency: "USD",
        owner_id: "u1",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
      },
    ]),

    getHoldings: vi.fn().mockResolvedValue({
      portfolio_id: "port-1",
      holdings: [
        {
          holding_id: "h-1",
          portfolio_id: "port-1",
          instrument_id: "ins-aapl",
          entity_id: "ent-aapl",
          ticker: "AAPL",
          name: "Apple Inc.",
          quantity: 10,
          average_cost: 170.0,
          current_price: 185.0,
          unrealised_pnl: 150.0,
          unrealised_pnl_pct: 0.0882,
          portfolio_weight: 0.55,
        },
        {
          holding_id: "h-2",
          portfolio_id: "port-1",
          instrument_id: "ins-msft",
          entity_id: "ent-msft",
          ticker: "MSFT",
          name: "Microsoft Corporation",
          quantity: 5,
          average_cost: 380.0,
          current_price: 395.0,
          unrealised_pnl: 75.0,
          unrealised_pnl_pct: 0.0394,
          portfolio_weight: 0.45,
        },
      ],
      total_value: 3825.0,
      total_cost: 3650.0,
      total_unrealised_pnl: 175.0,
      total_unrealised_pnl_pct: 0.0479,
    }),

    getBatchQuotes: vi.fn().mockResolvedValue({
      quotes: {
        "ins-aapl": {
          instrument_id: "ins-aapl",
          ticker: "AAPL",
          price: 185.0,
          change: 1.5,
          change_pct: 0.82,
          timestamp: "2026-04-18T15:00:00Z",
          volume: 45_000_000,
        },
        "ins-msft": {
          instrument_id: "ins-msft",
          ticker: "MSFT",
          price: 395.0,
          change: -2.0,
          change_pct: -0.50,
          timestamp: "2026-04-18T15:00:00Z",
          volume: 22_000_000,
        },
      },
    }),

    getTransactions: vi.fn().mockResolvedValue({
      transactions: [
        {
          transaction_id: "tx-1",
          portfolio_id: "port-1",
          instrument_id: "ins-aapl",
          ticker: "AAPL",
          asset_class: "equity",
          type: "BUY" as const,
          quantity: 10,
          price: 170.0,
          fee: 1.0,
          amount: null,
          currency: "USD",
          executed_at: "2026-03-01T10:00:00Z",
          notes: null,
        },
        {
          transaction_id: "tx-2",
          portfolio_id: "port-1",
          instrument_id: "ins-nvda",
          ticker: "NVDA",
          asset_class: "equity",
          type: "SELL" as const,
          quantity: 3,
          price: 820.0,
          fee: 1.5,
          amount: null,
          currency: "USD",
          executed_at: "2026-03-15T14:30:00Z",
          notes: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 100,
    }),

    getWatchlists: vi.fn().mockResolvedValue([
      {
        watchlist_id: "wl-1",
        name: "Tech Watch",
        owner_id: "u1",
        members: [
          {
            entity_id: "ent-nvda",
            instrument_id: "ins-nvda",
            ticker: "NVDA",
            name: "NVIDIA Corporation",
            added_at: "2026-04-10T09:00:00Z",
          },
        ],
        member_count: 1,
        created_at: "2026-04-10T09:00:00Z",
        updated_at: "2026-04-12T09:00:00Z",
      },
    ]),

    getBrokerageConnections: vi.fn().mockResolvedValue([]),
    getPortfolioBundle: vi.fn().mockRejectedValue(new Error("404")),
    getPortfolioPerformance: vi.fn().mockRejectedValue(new Error("no data")),
    getRealizedPnL: vi.fn().mockRejectedValue(new Error("no data")),
    getCompanyOverview: vi.fn().mockResolvedValue(null),
    getBatchOhlcvBars: vi.fn().mockResolvedValue({ results: [] }),
    getExposure: vi.fn().mockRejectedValue(new Error("no data")),

    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: {
        user_id: "u1",
        tenant_id: "t1",
        email: "trader@example.com",
        name: "Test Trader",
        avatar_url: null,
      },
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

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = makeQueryClient();
  return (
    <NuqsTestingAdapter searchParams="">
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </NuqsTestingAdapter>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PortfolioPage — W2 overview (no tabs)", () => {
  it("renders holding tickers after data loads", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // AAPL should be visible in the holdings table (W2 renders inline, no tab switch).
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });
  });

  it("renders MSFT holding in the table", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getAllByText("MSFT").length).toBeGreaterThan(0);
    });
  });

  it("renders KPI strip with Total Value label", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Total Value")).toBeInTheDocument();
    });
  });

  it("has no Holdings/Transactions/Watchlist tab buttons (W2 removed tabs)", async () => {
    render(<PortfolioPage />, { wrapper });

    // Wait for load to complete
    await waitFor(() => {
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });

    // WHY role=tab: the old tabs used <TabsTrigger> which has role="tab".
    // W2 removes all <Tabs> from the page — no elements with role="tab" should exist.
    expect(screen.queryByRole("tab", { name: "Holdings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Transactions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Watchlist" })).not.toBeInTheDocument();
  });

  it("renders Recent Activity strip (RecentActivityStrip replaces RecentActivityFeed)", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // WHY "Recent Activity": the RecentActivityStrip header label (§4.14).
      // This asserts the W2 activity strip is mounted below the holdings table.
      expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    });
  });
});
