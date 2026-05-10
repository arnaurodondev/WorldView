/**
 * __tests__/plan-0053-bd-widgets.test.tsx — Holdings tab widget smoke tests.
 *
 * One happy-path render check per component on the Holdings tab. Heavy
 * snapshotting is intentionally avoided — these tests pin the contract that
 * each widget renders without throwing on a typical data shape and the key
 * user-visible affordance (header label, primary number) appears.
 *
 * UPDATED in PLAN-0088 Wave E (2026-05-09): the tests for CashManagementCard,
 * RealizedPnLChart, and DividendIncomeTimeline are replaced by tests for the
 * single-row strips that took their place — CashRow, RealizedPnLSparkline,
 * DividendYTDStrip. The deleted components are not reinstated; the
 * replacement components carry forward the contract that each widget shows
 * its header label + primary number on a typical data shape.
 *
 * Mocks the gateway and useAuth so we never hit the network.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Shared gateway mocks ────────────────────────────────────────────────────

const mockExposure = vi.fn();
const mockTransactions = vi.fn();
const mockBrokerageConnections = vi.fn();
const mockRealizedPnL = vi.fn();
const mockTopNews = vi.fn();
const mockPortfolios = vi.fn();
const mockHoldings = vi.fn();
const mockConcentration = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getExposure: mockExposure,
    getTransactions: mockTransactions,
    getBrokerageConnections: mockBrokerageConnections,
    getRealizedPnL: mockRealizedPnL,
    getTopNews: mockTopNews,
    getPortfolios: mockPortfolios,
    getHoldings: mockHoldings,
    getConcentration: mockConcentration,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// PLAN-0088 Wave E: replacement strip components.
import { CashRow } from "@/components/portfolio/CashRow";
import { RecentActivityFeed } from "@/components/portfolio/RecentActivityFeed";
import { DividendYTDStrip } from "@/components/portfolio/DividendYTDStrip";
import { RealizedPnLSparkline } from "@/components/portfolio/RealizedPnLSparkline";
import { ConcentrationStrip } from "@/components/portfolio/ConcentrationStrip";
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

// ── CashRow (PLAN-0088 E-1, replaces CashManagementCard) ────────────────────

describe("CashRow (PLAN-0088 E-1)", () => {
  it("renders the cash label and the dollar amount from /exposure", async () => {
    mockExposure.mockResolvedValue({
      invested: 8000,
      cash: 2000,
      gross_exposure_pct: 0.8,
      net_exposure_pct: 0.8,
      leverage: 1,
      prices_stale: false,
      prices_as_of: null,
    });

    render(<CashRow portfolioId="p1" />, { wrapper: makeWrapper() });

    // Cash header label appears as a small uppercase caption in the strip.
    await waitFor(() => expect(screen.getByText("CASH")).toBeInTheDocument());
    // BUYING POWER + SWEEP RATE are placeholder cells with em-dashes —
    // verify their captions render so the row doesn't silently regress.
    expect(screen.getByText("BUYING POWER")).toBeInTheDocument();
    expect(screen.getByText("SWEEP RATE")).toBeInTheDocument();
  });
});

// ── ConcentrationStrip (PLAN-0088 E-3) ──────────────────────────────────────

describe("ConcentrationStrip (PLAN-0088 E-3)", () => {
  it("renders HHI value and the diversified/moderate/concentrated label", async () => {
    mockConcentration.mockResolvedValue({
      portfolio_id: "p1",
      hhi: 1847,
      label: "moderate",
      top_3_share_pct: 71.3,
      positions_count: 5,
      top_positions: [],
      prices_stale: false,
    });

    render(<ConcentrationStrip portfolioId="p1" />, { wrapper: makeWrapper() });

    // HHI label and number appear; "moderate" badge follows.
    await waitFor(() => expect(screen.getByText("HHI")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("1,847")).toBeInTheDocument());
    expect(screen.getByText("moderate")).toBeInTheDocument();
    // Position count caption.
    expect(screen.getByText(/5 names/)).toBeInTheDocument();
  });
});

// ── RecentActivityFeed (kept; broker-gated in HoldingsTab) ──────────────────

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
    await waitFor(() => expect(screen.getByText("SYNC")).toBeInTheDocument());
  });
});

// ── DividendYTDStrip (PLAN-0088 E-1, replaces DividendIncomeTimeline) ───────

describe("DividendYTDStrip (PLAN-0088 E-1)", () => {
  it("aggregates DIVIDEND transactions into a single YTD total row", async () => {
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
          executed_at: `${thisYear}-02-15T10:00:00Z`,
          notes: null,
        },
      ],
      total: 1,
      offset: 0,
      limit: 200,
    });

    render(<DividendYTDStrip portfolioId="p1" />, { wrapper: makeWrapper() });

    // Strip caption appears.
    await waitFor(() => expect(screen.getByText("DIV YTD")).toBeInTheDocument());
    // 1-ticker caption appears.
    await waitFor(() =>
      expect(screen.getByText(/across 1 ticker/)).toBeInTheDocument(),
    );
  });
});

// ── RealizedPnLSparkline (PLAN-0088 E-2, replaces RealizedPnLChart) ─────────

describe("RealizedPnLSparkline (PLAN-0088 E-2)", () => {
  it("renders the realised total + ST/LT split + disposal count", async () => {
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

    render(<RealizedPnLSparkline portfolioId="p1" />, { wrapper: makeWrapper() });

    // Headline caption + ST/LT/disposals captions.
    await waitFor(() => expect(screen.getByText("REALISED YTD")).toBeInTheDocument());
    expect(screen.getByText("ST")).toBeInTheDocument();
    expect(screen.getByText("LT")).toBeInTheDocument();
    expect(screen.getByText("DISPOSALS")).toBeInTheDocument();
  });
});

// ── PortfolioNewsWidget filter strip (PLAN-0053 T-D-4-01) ───────────────────

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

    // Sort buttons — preserved from the original PLAN-0053 contract.
    await waitFor(() => expect(screen.getByText("IMPACT")).toBeInTheDocument());
    expect(screen.getByText("DATE")).toBeInTheDocument();
    // Tier pills — the four canonical tier labels.
    expect(screen.getByText("LIGHT")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText("DEEP")).toBeInTheDocument();
  });
});
