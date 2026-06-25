/**
 * __tests__/portfolio.test.tsx — Unit tests for the Portfolio page
 *
 * WHY THIS EXISTS: The portfolio page is a data-dense, multi-tab page with
 * several async data loads. Tests verify that each tab renders the expected
 * content and that styling invariants (BUY=green, SELL=red) are upheld.
 *
 * WHY MOCK GATEWAY: We control exactly what data each query returns.
 * Without mocks, tests would depend on a live S9 instance and be flaky.
 *
 * WHAT IS TESTED:
 *   1. Holdings tab renders after data loads
 *   2. Transactions tab shows transaction data
 *   3. Watchlist tab renders with member data
 *   4. BUY transaction styled with correct (positive/green) class
 *   5. SELL transaction styled with correct (negative/red) class
 *
 * DATA SOURCE: Mocked gateway client — controlled, deterministic
 * DESIGN REFERENCE: PRD-0028 §6.5 Portfolio
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
// PLAN-0059 C-6: PortfolioPage now reads URL state via nuqs (active tab +
// equity period). The testing adapter provides a stub router so the hooks
// don't crash; empty searchParams gives the documented defaults.
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PortfolioPage from "@/app/(app)/portfolio/page";

// ── Next.js navigation mock ────────────────────────────────────────────────────
// WHY: PortfolioPage calls useRouter().push() for row clicks.
// In unit tests the App Router is not mounted — mock to avoid "invariant" error.
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
// WHY: PortfolioPage calls useAuth() to get the access token for S9 requests.
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
// WHY: We return deterministic sample data so assertions are stable.
// All six queries the page makes are mocked here.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    // Query 1: portfolios list — single portfolio
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

    // Query 2: holdings — two positions
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

    // Query 3: batch quotes for holdings
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

    // Query 4: transactions — one BUY, one SELL
    getTransactions: vi.fn().mockResolvedValue({
      transactions: [
        {
          transaction_id: "tx-1",
          portfolio_id: "port-1",
          instrument_id: "ins-aapl",
          ticker: "AAPL",
          type: "BUY" as const,
          quantity: 10,
          price: 170.0,
          fee: 1.0,
          currency: "USD",
          executed_at: "2026-03-01T10:00:00Z",
          notes: null,
        },
        {
          transaction_id: "tx-2",
          portfolio_id: "port-1",
          instrument_id: "ins-nvda",
          ticker: "NVDA",
          type: "SELL" as const,
          quantity: 3,
          price: 820.0,
          fee: 1.5,
          currency: "USD",
          executed_at: "2026-03-15T14:30:00Z",
          notes: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 100,
    }),

    // Query 5: watchlists
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
          {
            entity_id: "ent-amd",
            instrument_id: "ins-amd",
            ticker: "AMD",
            name: "Advanced Micro Devices",
            added_at: "2026-04-12T09:00:00Z",
          },
        ],
        member_count: 2,
        created_at: "2026-04-10T09:00:00Z",
        updated_at: "2026-04-12T09:00:00Z",
      },
    ]),

    // Query 6b (R1 sprint): exposure — feeds the CASH / BUYING PWR KPI tiles.
    // Decimal fields arrive pre-parsed because lib/api/portfolios.ts
    // transforms at the gateway boundary; the mock returns the post-transform
    // ExposureResponse shape (numbers).
    getExposure: vi.fn().mockResolvedValue({
      invested: 95_000,
      cash: 12_345.67,
      gross_exposure_pct: 0.95,
      net_exposure_pct: 0.95,
      leverage: 1,
      prices_stale: false,
      prices_as_of: null,
    }),

    // Auth plumbing (required by AuthContext refresh logic)
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

/**
 * makeQueryClient — fresh QueryClient per test with retries disabled
 *
 * WHY retry: false: TanStack Query retries failed queries by default.
 * In unit tests this causes tests to hang waiting for retry delays.
 * With retry: false, errors surface immediately.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

/**
 * wrapper — React tree provider for all tests
 * WHY: TanStack Query useQuery() requires QueryClientProvider in the tree.
 */
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
  it("renders 'Holdings' tab trigger as a role=tab element", async () => {
    render(<PortfolioPage />, { wrapper });

    // WHY waitFor: the component starts in loading state, then queries resolve.
    // We use role="tab" to uniquely target the tab trigger, not the CardTitle.
    await waitFor(() => {
      // getByRole("tab", {name:...}) uniquely matches the TabsTrigger button
      expect(screen.getByRole("tab", { name: "Holdings" })).toBeInTheDocument();
    });
  });

  it("renders holding tickers after data loads", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // Holdings tab is active by default — AAPL should be visible.
      // PLAN-0088 Wave E: AAPL now legitimately appears in multiple places
      // (table cell + HoldingLotsPanel ticker dropdown option + PositionBarHeat
      // bar label). getAllByText asserts the same intent — at least one
      // occurrence of the ticker is rendered — without restricting how many.
      expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    });
  });

  it("renders MSFT holding in the table", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // Same multi-render rationale as the AAPL test above.
      expect(screen.getAllByText("MSFT").length).toBeGreaterThan(0);
    });
  });

  it("renders P&L summary tiles", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // WHY check for "Total Value" label:
      // The PnlSummaryRow component renders this as a KPI tile header.
      expect(screen.getByText("Total Value")).toBeInTheDocument();
    });
  });

  it("renders Cash and Buying Pwr KPI tiles from the exposure endpoint (R1 sprint)", async () => {
    // WHY: BP-517-class regression guard — the cash/buyingPower props were
    // never wired from the page to PortfolioKPIStrip, so both tiles rendered
    // a permanent "—" even though GET /exposure returned real numbers. This
    // test pins the full data path: usePortfolioData → exposure → page props.
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("kpi-cash")).toHaveTextContent("12,345.67");
    });
    // Buying power = cash for v1 cash accounts (margin is v2).
    expect(screen.getByTestId("kpi-buying-pwr")).toHaveTextContent("12,345.67");
  });
});

describe("PortfolioPage — Transactions tab", () => {
  it("renders 'Transactions' tab trigger as a role=tab element", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // role=tab uniquely targets the TabsTrigger button, not the CardTitle
      expect(screen.getByRole("tab", { name: "Transactions" })).toBeInTheDocument();
    });
  });

  it("renders BUY transaction with positive color class after switching tabs", async () => {
    // WHY userEvent (not .click()): Radix UI TabsTrigger listens to pointer events.
    // jsdom's .click() fires only the click event; userEvent.click() fires the full
    // pointer event sequence (pointerdown, pointerup, click) which Radix requires.
    const user = userEvent.setup();
    const { container } = render(<PortfolioPage />, { wrapper });

    // Wait for the page to fully render (tab triggers appear when portfolios load)
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Transactions" })).toBeInTheDocument();
    });

    // Click the Transactions tab trigger with userEvent (fires pointer events)
    await user.click(screen.getByRole("tab", { name: "Transactions" }));

    // Wait for transaction data to appear in the now-active tab panel
    await waitFor(() => {
      // The BUY transaction type cell should be visible
      const buyEl = container.querySelector('[data-testid="tx-type-tx-1"]');
      expect(buyEl).toBeInTheDocument();
      // WHY check for text-positive: this is the spec-mandated positive color
      // (Bloomberg Dark positive teal), applied by cn() in TransactionsTable
      expect(buyEl?.className).toContain("text-positive");
    });
  });

  it("renders SELL transaction with negative color class", async () => {
    const user = userEvent.setup();
    const { container } = render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Transactions" })).toBeInTheDocument();
    });

    // Switch to Transactions tab with userEvent
    await user.click(screen.getByRole("tab", { name: "Transactions" }));

    await waitFor(() => {
      const sellEl = container.querySelector('[data-testid="tx-type-tx-2"]');
      expect(sellEl).toBeInTheDocument();
      // WHY check for text-negative: this is the spec-mandated negative color
      // (Bloomberg Dark negative red), applied when type === "SELL"
      expect(sellEl?.className).toContain("text-negative");
    });
  });
});

describe("PortfolioPage — Watchlist tab", () => {
  it("renders 'Watchlist' tab trigger as a role=tab element", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      // role=tab uniquely targets the TabsTrigger button, not the CardTitle
      expect(screen.getByRole("tab", { name: "Watchlist" })).toBeInTheDocument();
    });
  });

  it("renders watchlist member tickers after switching tabs", async () => {
    // WHY userEvent: same reason as Transactions tab — Radix needs pointer events
    const user = userEvent.setup();
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Watchlist" })).toBeInTheDocument();
    });

    // Switch to Watchlist tab using the role=tab trigger
    await user.click(screen.getByRole("tab", { name: "Watchlist" }));

    await waitFor(() => {
      // NVDA is in the mock watchlist — should render in the active tab panel
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });
  });

  it("renders watchlist name after data loads", async () => {
    const user = userEvent.setup();
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Watchlist" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: "Watchlist" }));

    await waitFor(() => {
      // "Tech Watch" is the mock watchlist name. Since the 2026-06-10
      // watchlist density pass it legitimately appears TWICE: in the
      // watchlist tab bar AND in the new group-header row above the table
      // ("Tech Watch · N tickers") — getAllByText keeps the original
      // assertion (the name renders) while accepting the second surface.
      expect(screen.getAllByText("Tech Watch").length).toBeGreaterThanOrEqual(1);
    });
  });
});
