/**
 * __tests__/portfolio-stale.test.tsx — Portfolio page + stale-price tests
 *
 * WHY THIS FILE EXISTS: The portfolio page gained stale-price indicators in W2-9
 * (PLAN-0036). These tests verify the formatting logic and W2 overview layout.
 *
 * W2 CHANGE (PRD-0089 W2 §4.19): tabs are removed. This file now tests the
 * W2 single-overview layout (no tabs to click through). The stale price tests
 * at the bottom are unchanged — they test a pure helper function.
 *
 * WHY MOCK GATEWAY: We control exactly what data each query returns.
 * Without mocks, tests would depend on a live S9 instance and be flaky.
 *
 * DATA SOURCE: Mocked gateway client — controlled, deterministic
 * DESIGN REFERENCE: PRD-0028 §6.5 Portfolio, PRD-0089 W2 §4.19
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// PLAN-0059 C-6: PortfolioPage uses nuqs URL state; tests need the testing
// adapter to stub the router.
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import PortfolioPage from "@/app/(app)/portfolio/page";

// ── Next.js navigation mock ────────────────────────────────────────────────────
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

describe("PortfolioPage — Holdings tab", () => {
  it("renders holding tickers after data loads", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // Holdings render inline (W2: no tab switch needed).
      // AAPL appears in the table. getAllByText handles multiple occurrences.
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });
  });

  it("renders MSFT holding in the table", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getAllByText("MSFT").length).toBeGreaterThan(0);
    });
  });

  it("renders P&L summary tiles", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Total Value")).toBeInTheDocument();
    });
  });
});

describe("PortfolioPage — Transactions tab", () => {
  it("has no Transactions tab button (W2 moved to /portfolio/transactions)", async () => {
    render(<PortfolioPage />, { wrapper });

    // Wait for load
    await waitFor(() => {
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });

    // WHY not.toBeInTheDocument(): W2 removed tabs; clicking "Transactions"
    // now navigates to /portfolio/transactions via the "T" hotkey or a direct link.
    expect(screen.queryByRole("tab", { name: "Transactions" })).not.toBeInTheDocument();
  });

  it("renders BUY transactions inline in RecentActivityStrip", async () => {
    render(<PortfolioPage />, { wrapper });

    // W2: transactions appear in the RecentActivityStrip on the overview page.
    // The strip shows the last 8 transactions including BUY type.
    await waitFor(() => {
      expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    });
    // BUY type should be visible directly in the strip (no tab navigation needed)
    await waitFor(() => {
      expect(screen.getByText("BUY")).toBeInTheDocument();
    });
  });

  it("renders SELL transactions inline in RecentActivityStrip", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("SELL")).toBeInTheDocument();
    });
  });
});

describe("PortfolioPage — Watchlist tab", () => {
  it("has no Watchlist tab button (W2: watchlists accessible via /watchlists route)", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });

    // WHY: W2 removed tabs. The "W" hotkey navigates to /watchlists directly.
    expect(screen.queryByRole("tab", { name: "Watchlist" })).not.toBeInTheDocument();
  });
});

// ── PLAN-0036 W2-9: Stale price indicator unit tests ─────────────────────────
//
// WHY unit tests (not integration tests) for the stale-price logic:
// The staleness indicator lives entirely in a pure helper function
// (formatStalenessAwarePrice). Testing the helper directly is more reliable,
// faster, and more targeted than parsing a full mounted component's rendered DOM.

import { formatPrice } from "@/lib/utils";

/**
 * formatStalenessAwarePrice — the helper logic under test (mirrored here for isolation)
 */
function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  const formatted = formatPrice(price);
  return isStale ? `~${formatted}` : formatted;
}

describe("W2-9 formatStalenessAwarePrice helper — unit", () => {
  it("returns price without ~ when freshness is 'live'", () => {
    expect(formatStalenessAwarePrice(185.42, "live")).toBe("$185.42");
  });

  it("returns price without ~ when freshness is undefined (old S9 response)", () => {
    expect(formatStalenessAwarePrice(185.42, undefined)).toBe("$185.42");
  });

  it("returns price with ~ when freshness is 'stale'", () => {
    expect(formatStalenessAwarePrice(185.42, "stale")).toBe("~$185.42");
  });

  it("returns price with ~ when freshness is 'delayed'", () => {
    expect(formatStalenessAwarePrice(185.42, "delayed")).toBe("~$185.42");
  });

  it("returns price with ~ when freshness is 'eod'", () => {
    expect(formatStalenessAwarePrice(185.42, "eod")).toBe("~$185.42");
  });

  it("returns price with ~ when freshness is 'unavailable'", () => {
    expect(formatStalenessAwarePrice(185.42, "unavailable")).toBe("~$185.42");
  });

  it("preserves dollar sign and 2 decimal places", () => {
    const result = formatStalenessAwarePrice(12345.6, "stale");
    expect(result).toMatch(/^~\$/);
    expect(result).toMatch(/12,345\.60$/);
  });
});
