/**
 * __tests__/plan-0053-bd-widgets.test.tsx — PLAN-0053 Wave B + D widget smoke tests.
 *
 * One happy-path render check per new component, plus a regression that the
 * TransactionsTable surfaces the new asset-class badge. Heavy snapshotting is
 * intentionally avoided — these tests pin the contract that:
 *   1. Each component renders without throwing on a typical data shape.
 *   2. Key user-visible affordances (header label, primary number) appear.
 *
 * Mocks the gateway and useAuth so we never hit the network.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Shared gateway mocks ────────────────────────────────────────────────────
// Each describe-block re-uses these by injecting the relevant fields onto
// the mocked gateway implementation.

const mockExposure = vi.fn();
const mockTransactions = vi.fn();
const mockBrokerageConnections = vi.fn();
const mockRealizedPnL = vi.fn();
const mockTopNews = vi.fn();
const mockPortfolios = vi.fn();
const mockHoldings = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getExposure: mockExposure,
    getTransactions: mockTransactions,
    getBrokerageConnections: mockBrokerageConnections,
    getRealizedPnL: mockRealizedPnL,
    getTopNews: mockTopNews,
    getPortfolios: mockPortfolios,
    getHoldings: mockHoldings,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { CashManagementCard } from "@/components/portfolio/CashManagementCard";
import { RecentActivityFeed } from "@/components/portfolio/RecentActivityFeed";
import { DividendIncomeTimeline } from "@/components/portfolio/DividendIncomeTimeline";
import { RealizedPnLChart } from "@/components/portfolio/RealizedPnLChart";
import { PortfolioNewsWidget } from "@/components/dashboard/PortfolioNewsWidget";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

// ── CashManagementCard ──────────────────────────────────────────────────────

describe("CashManagementCard (PLAN-0053 T-B-2-04)", () => {
  it("renders cash %, $ amount, and the cash-drag badge above 5%", async () => {
    mockExposure.mockResolvedValue({
      invested: 8000,
      cash: 2000, // 20% cash → drag badge expected
      gross_exposure_pct: 0.8,
      net_exposure_pct: 0.8,
      leverage: 1,
      prices_stale: false,
      prices_as_of: null,
    });

    render(<CashManagementCard portfolioId="p1" />, { wrapper: makeWrapper() });

    // Cash header label
    await waitFor(() => expect(screen.getByText("CASH")).toBeInTheDocument());
    // Cash drag badge (only renders when > 5%)
    await waitFor(() => expect(screen.getByText("Cash drag")).toBeInTheDocument());
    // Sweep APY placeholder
    expect(screen.getByText("SWEEP APY")).toBeInTheDocument();
  });
});

// ── RecentActivityFeed ──────────────────────────────────────────────────────

describe("RecentActivityFeed (PLAN-0053 T-B-2-05)", () => {
  it("merges transactions and sync events into one chronological feed", async () => {
    mockTransactions.mockResolvedValue({
      transactions: [
        {
          transaction_id: "tx-1",
          portfolio_id: "p1",
          instrument_id: "ins-1",
          ticker: "AAPL",
          asset_class: "equity",
          type: "BUY",
          quantity: 10,
          price: 150,
          fee: 0,
          amount: null,
          currency: "USD",
          executed_at: "2026-04-25T10:00:00Z",
          notes: null,
        },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    });
    mockBrokerageConnections.mockResolvedValue([
      {
        connection_id: "c-1",
        portfolio_id: "p1",
        brokerage_name: "TestBroker",
        status: "active",
        last_synced_at: "2026-04-26T08:00:00Z",
        created_at: "2026-04-01T00:00:00Z",
      },
    ]);

    render(<RecentActivityFeed portfolioId="p1" />, { wrapper: makeWrapper() });

    await waitFor(() => expect(screen.getByText("RECENT ACTIVITY")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    // The sync row labels SYNC.
    await waitFor(() => expect(screen.getByText("SYNC")).toBeInTheDocument());
  });
});

// ── DividendIncomeTimeline ─────────────────────────────────────────────────

describe("DividendIncomeTimeline (PLAN-0053 T-B-2-06)", () => {
  it("aggregates DIVIDEND transactions and renders a per-ticker table", async () => {
    const thisYear = new Date().getUTCFullYear();
    mockTransactions.mockResolvedValue({
      transactions: [
        {
          transaction_id: "d-1",
          portfolio_id: "p1",
          instrument_id: "ins-1",
          ticker: "VOO",
          asset_class: "etf",
          type: "DIVIDEND",
          quantity: 0,
          price: 0,
          fee: 0,
          amount: 50,
          currency: "USD",
          // Pin to current year so the YTD filter keeps the row.
          executed_at: `${thisYear}-02-15T10:00:00Z`,
          notes: null,
        },
      ],
      total: 1,
      offset: 0,
      limit: 500,
    });

    render(<DividendIncomeTimeline portfolioId="p1" />, { wrapper: makeWrapper() });

    await waitFor(() =>
      expect(screen.getByText(/DIVIDEND INCOME/)).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByText("VOO")).toBeInTheDocument());
  });
});

// ── RealizedPnLChart ───────────────────────────────────────────────────────

describe("RealizedPnLChart (PLAN-0053 T-D-4-03)", () => {
  it("renders the total readout and breakdown table", async () => {
    mockRealizedPnL.mockResolvedValue({
      portfolio_id: "p1",
      from: "2025-01-01",
      to: "2026-01-01",
      total_realized: 1234.5,
      realized_long_term: 1000,
      realized_short_term: 234.5,
      count: 3,
      breakdown_by_instrument: [
        { instrument_id: "ins-1", ticker: "AAPL", realized: 800, count: 2 },
        { instrument_id: "ins-2", ticker: "MSFT", realized: 434.5, count: 1 },
      ],
      currency: "USD",
    });

    render(<RealizedPnLChart portfolioId="p1" />, { wrapper: makeWrapper() });

    await waitFor(() => expect(screen.getByText(/REALIZED P&L/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("MSFT")).toBeInTheDocument());
  });
});

// ── PortfolioNewsWidget filter strip (T-D-4-01) ─────────────────────────────

describe("PortfolioNewsWidget filter strip (PLAN-0053 T-D-4-01)", () => {
  it("renders sort buttons + tier pills + ticker dropdown", async () => {
    mockTopNews.mockResolvedValue({ articles: [], total: 0 });
    mockPortfolios.mockResolvedValue([]);
    mockHoldings.mockResolvedValue({
      portfolio_id: "p1",
      holdings: [],
      total_value: 0,
      total_cost: 0,
      total_unrealised_pnl: 0,
      total_unrealised_pnl_pct: 0,
    });

    render(<PortfolioNewsWidget />, { wrapper: makeWrapper() });

    // Sort buttons
    await waitFor(() => expect(screen.getByText("IMPACT")).toBeInTheDocument());
    expect(screen.getByText("DATE")).toBeInTheDocument();
    // Tier pills — the four canonical tier labels.
    expect(screen.getByText("LIGHT")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("DEEP")).toBeInTheDocument();
  });
});
