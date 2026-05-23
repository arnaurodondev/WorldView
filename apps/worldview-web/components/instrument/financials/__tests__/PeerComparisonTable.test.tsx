/**
 * PeerComparisonTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the composition contract for the 5-peers + self table.
 * Verifies self-row renders from fundamentals, peer rows render from peersData,
 * the "—" placeholder appears for null returns, and undefined data shows the
 * empty-state label.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PeerComparisonTable } from "@/components/instrument/financials/PeerComparisonTable";
import type { PeersResponse, Fundamentals } from "@/types/api";

// WHY mock next/navigation: PeerComparisonTable uses useRouter for peer-row clicks.
// vi.mock is hoisted automatically by vitest.
import { vi } from "vitest";
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const FUNDAMENTALS: Fundamentals = {
  instrument_id: "aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  market_cap: 3_000_000_000_000,
  pe_ratio: 28.5,
  forward_pe: 26.0,
  price_to_book: 45.0,
  price_to_sales: 7.8,
  ev_to_ebitda: 20.0,
  gross_margin: 0.443,
  operating_margin: 0.302,
  net_margin: 0.254,
  roe: 1.6,
  roa: 0.28,
  revenue_growth_yoy: 0.05,
  earnings_growth_yoy: 0.07,
  dividend_yield: 0.006,
  payout_ratio: 0.15,
  debt_to_equity: 1.8,
  current_ratio: 0.99,
  quick_ratio: 0.94,
  week_52_high: 260.1,
  week_52_low: 164.08,
  daily_return: 0.012,
  analyst_strong_buy_count: 25,
  analyst_buy_count: 5,
  analyst_hold_count: 10,
  analyst_sell_count: 4,
  analyst_strong_sell_count: 1,
  analyst_rating: 4.2,
  analyst_target_price: 215.0,
  updated_at: "2026-05-19T12:00:00Z",
};

const PEERS_RESPONSE: PeersResponse = {
  instrument_id: "aapl",
  industry: "Technology Hardware",
  peers: [
    {
      instrument_id: "msft",
      ticker: "MSFT",
      name: "Microsoft Corp",
      market_cap: 2_900_000_000_000,
      pe_ratio: 35.2,
      // WHY 0.184: return_1y from S3 is a decimal fraction (0.184 = 18.4%).
      // S3 does NOT multiply return_1y by 100 (unlike change_pct which it does).
      return_1y: 0.184,
      // WHY 0.3: change_pct from S3 is already a percentage (0.3 = +0.30%).
      change_pct: 0.3,
    },
    {
      instrument_id: "googl",
      ticker: "GOOGL",
      name: "Alphabet Inc",
      market_cap: 2_000_000_000_000,
      pe_ratio: 22.1,
      return_1y: null,
      change_pct: -0.5,
    },
  ],
};

describe("PeerComparisonTable", () => {
  it("renders section header", () => {
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/PEER COMPARISON/)).toBeInTheDocument();
  });

  it("renders self-row with ticker from fundamentals", () => {
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });

  it("renders peer tickers", () => {
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
  });

  it("renders — for null return_1y", () => {
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // GOOGL has null return_1y → should show "—"
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("formats return_1y as decimal fraction (18.4% shown as +18.40%)", () => {
    // WHY this test: return_1y from S3 is a decimal fraction (0.184 = 18.4%).
    // Previously fmtPct divided by 100 again → 0.001840 → "+0.18%" (wrong).
    // After fix, fmtDecimalPct calls formatPercent(0.184) → "+18.40%".
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // MSFT has return_1y=0.184 → should render "+18.40%"
    expect(screen.getByText("+18.40%")).toBeInTheDocument();
  });

  it("formats change_pct as already-percentage (0.3 shown as +0.30%)", () => {
    // WHY this test: change_pct from S3 is already a percentage (0.3 = +0.30%).
    // fmtPctDirect calls formatPercentDirect(0.3) → "+0.30%".
    render(
      <PeerComparisonTable
        peersData={PEERS_RESPONSE}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    // MSFT has change_pct=0.3 → should render "+0.30%"
    expect(screen.getByText("+0.30%")).toBeInTheDocument();
  });

  it("renders loading state when peersData is undefined", () => {
    render(
      <PeerComparisonTable
        peersData={undefined}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/peer data loading/i)).toBeInTheDocument();
  });

  it("renders empty state when peers array is empty", () => {
    render(
      <PeerComparisonTable
        peersData={{ instrument_id: "aapl", industry: null, peers: [] }}
        instrumentId="aapl"
        fundamentals={FUNDAMENTALS}
      />,
    );
    expect(screen.getByText(/no peers available/i)).toBeInTheDocument();
  });
});
