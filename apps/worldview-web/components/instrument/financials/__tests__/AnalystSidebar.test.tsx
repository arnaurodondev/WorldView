/**
 * components/instrument/financials/__tests__/AnalystSidebar.test.tsx
 *
 * WHY THIS EXISTS: PLAN-0090 §T-C-04 pins one composition contract on
 * the Financials right-rail (PRD-0088 §6.8):
 *
 *   1. test_AnalystSidebar_renders_consensus_bar
 *      When at least one of the 5 bucket counts is non-null, the
 *      <AnalystMiniBar/> stacked-consensus bar MUST render inside the
 *      sidebar. The sidebar's whole reason for existing is to surface the
 *      consensus pill next to the metrics grid; a silent regression that
 *      drops the bar (e.g. accidental conditional gate, props rename)
 *      would eliminate the only Wall-Street opinion artefact on the page.
 *
 * WHY assert on the bar's text summary "{B}B · {H}H · {S}S" (rather than
 * on a DOM-internal selector): AnalystMiniBar deliberately writes this
 * summary string as part of its rendered output — it is a stable, visible
 * contract owned by AnalystMiniBar's own test (`AnalystMiniBar.test.tsx`).
 * Reusing it here keeps this test loosely coupled to the bar's internals
 * (no querySelectorAll on `[style*=width]`) while still proving the bar
 * mounted. If the bar fails to mount, the summary text is absent.
 *
 * WHY mock hook-based child panels: T-24 redesigned AnalystSidebar as a
 * thin shell composing 7 panels. Three panels (BeatMissHistoryPanel,
 * AIBriefPanel, CompanySnapshotPanel) use TanStack Query / auth hooks.
 * Mocking them here keeps the test focused on the sidebar shell's
 * composition contract — not on the panels' data-fetch internals, which
 * each panel's own test suite covers.
 *
 * WHY NOT also assert on null-coverage path: that scenario is covered by
 * AnalystMiniBar's own "all-null inputs" test. T-C-04 only requires the
 * positive-render contract here.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Mock hook-dependent panels ────────────────────────────────────────────────
// WHY mock these: they use TanStack Query and auth hooks; wiring a full
// QueryClientProvider + AuthContext would make this test about infrastructure,
// not about the sidebar's composition contract. Each panel has its own test.
vi.mock("@/components/instrument/financials/sidebar/BeatMissHistoryPanel", () => ({
  BeatMissHistoryPanel: () => <div data-testid="beat-miss-panel" />,
}));
vi.mock("@/components/instrument/financials/sidebar/AIBriefPanel", () => ({
  AIBriefPanel: () => <div data-testid="ai-brief-panel" />,
}));
vi.mock("@/components/instrument/financials/sidebar/CompanySnapshotPanel", () => ({
  CompanySnapshotPanel: () => <div data-testid="company-snapshot-panel" />,
}));

import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// Minimal Fundamentals fixture with analyst fields + required non-null stubs.
const FUNDAMENTALS: Fundamentals = {
  instrument_id: "test-id",
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
  // WHY 25/5/10/4/1: same split as original test — sum = 30B + 10H + 5S.
  analyst_strong_buy_count: 25,
  analyst_buy_count: 5,
  analyst_hold_count: 10,
  analyst_sell_count: 4,
  analyst_strong_sell_count: 1,
  analyst_rating: 4.2,
  analyst_target_price: 215.0,
  updated_at: "2026-05-19T12:00:00Z",
};

const SNAPSHOT: FundamentalsSnapshot = {
  instrument_id: "test-id",
  beta: 1.2,
  eps_ttm: 6.43,
  free_cash_flow: 108_000_000_000,
  operating_cash_flow: 118_000_000_000,
  capex: -10_000_000_000,
  fcf_margin: 0.26,
  net_debt_to_ebitda: 0.5,
  avg_volume_30d: 60_000_000,
  interest_coverage: null,
  credit_rating: null,
  updated_at: null,
};

describe("AnalystSidebar", () => {
  it("renders the AnalystMiniBar consensus bar when bucket counts are non-null", () => {
    render(
      <AnalystSidebar
        instrumentId="test-id"
        fundamentals={FUNDAMENTALS}
        snapshot={SNAPSHOT}
      />,
    );

    // WHY assert on the bar's summary text: presence of "30B · 10H · 5S"
    // can only happen if AnalystMiniBar mounted and ran its bucket-collapse
    // arithmetic. That is the cheapest proof that the bar is in the tree.
    expect(screen.getByText("30B · 10H · 5S")).toBeInTheDocument();

    // WHY also assert the section header is present: pins the sidebar's
    // own structural contract and catches accidental omission of the panel.
    expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
  });

  it("renders all 7 panel slots", () => {
    render(
      <AnalystSidebar
        instrumentId="test-id"
        fundamentals={FUNDAMENTALS}
        snapshot={SNAPSHOT}
      />,
    );

    // Section headers from pure panels.
    expect(screen.getByText("12-MO TARGET")).toBeInTheDocument();
    expect(screen.getByText("ESTIMATE REVISIONS")).toBeInTheDocument();
    expect(screen.getByText("TARGETS BY ANALYST")).toBeInTheDocument();
    // Mocked hook-dependent panels.
    expect(screen.getByTestId("beat-miss-panel")).toBeInTheDocument();
    expect(screen.getByTestId("ai-brief-panel")).toBeInTheDocument();
    expect(screen.getByTestId("company-snapshot-panel")).toBeInTheDocument();
  });
});
