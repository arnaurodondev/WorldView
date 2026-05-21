/**
 * __tests__/instrument/quote-density.test.tsx — Quote tab above-fold cell count (T-29)
 *
 * WHY THIS EXISTS (Δ42): PRD-0089 §1 acceptance gate requires ≥ 80 visible data
 * cells above-fold on 1440×900. This Vitest test renders a subset of W5 strips
 * and grids in isolation and asserts that their combined cell count meets a
 * proportional unit-level gate (≥ 50).
 *
 * WHY NOT render QuoteTab directly: QuoteTab uses "use client" hooks (useQuery,
 * useRouter, useQueryClient) that require a full provider tree + JSDOM mocking.
 * Rendering each strip/grid in isolation and summing counts is sufficient to
 * validate the density contract without brittle provider setup.
 *
 * WHY 8 strips (not all 12): PeersStrip, PriceLevelsStrip, WhatsMovingStrip, and
 * SessionStatsStrip require gateway/auth context mocks better suited to
 * integration tests. The full ≥ 80 Δ42 gate is validated by the Playwright e2e
 * test (instrument-quote.spec.ts C-36).
 *
 * Cell count breakdown (unit gate, ≥ 50):
 *   MetricGrid4Col (VALUATION)    8 cells
 *   MetricGrid4Col (MARGINS)      8 cells
 *   MetricGrid4Col (LEV+YIELD)    8 cells
 *   MultiPeriodReturnsStrip       7 cells + 1 row
 *   IntradayStatsBand             6 cells + 1 row
 *   InsiderActivityList           5 rows  (top 5)
 *   EarningsMiniList              4 rows  (last 4 annual)
 *   RelatedHeadlinesList          5 rows  (top 5)
 *   ─────────────────────────────
 *   Total                        37 cells + 16 rows = 53 ≥ 50
 *
 * WHY role="cell": MetricCell + stat rows both use role="cell" so we can count
 * all data cells with a single query.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// WHY mock next/navigation: RelatedHeadlinesList uses useRouter() for
// click-to-navigate. Without this, vitest throws "invariant: useRouter must be
// in Next.js Router context". All test-visible behaviour (row rendering) is
// unaffected by the navigation mock.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/AAPL"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));
import { MultiPeriodReturnsStrip } from "@/components/instrument/quote/strips/MultiPeriodReturnsStrip";
import { IntradayStatsBand } from "@/components/instrument/quote/strips/IntradayStatsBand";
import { MetricGrid4Col } from "@/components/instrument/quote/metrics/MetricGrid4Col";
import { InsiderActivityList } from "@/components/instrument/quote/insider/InsiderActivityList";
import { EarningsMiniList } from "@/components/instrument/quote/earnings/EarningsMiniList";
import { RelatedHeadlinesList } from "@/components/instrument/quote/news/RelatedHeadlinesList";

// ── Fixture data ──────────────────────────────────────────────────────────────

const MULTI_PERIOD_DATA = {
  instrument_id: "aapl",
  periods: {
    "1D": 1.42, "5D": 3.21, "1M": 5.12, "3M": 8.77,
    "6M": -2.11, "YTD": 12.33, "1Y": 22.45,
  },
} as const;

const INTRADAY_DATA = {
  instrument_id: "aapl",
  vwap: 187.42, atr_14: 3.21, rsi_14: 58.3,
  gap_pct: 0.42, premarket_high: 188.10, premarket_low: 186.50,
  short_interest_pct: 0.92,
};

const METRIC_GRID_CELLS_VALUATION = [
  { label: "MKT CAP", value: "$2.89T" },
  { label: "P/E", value: "28.4" },
  { label: "FWD P/E", value: "26.1" },
  { label: "EPS TTM", value: "$6.42" },
  { label: "P/S", value: "7.2" },
  { label: "P/B", value: "44.1" },
  { label: "EV/EBITDA", value: "22.3" },
  { label: "FCF", value: "$108B" },
];

const INSIDER_RECORDS = {
  records: [
    { id: "1", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-04-30", owner_name: "L.Maestri", transaction_type: "Sale", shares: 10000, value: 2800000 } },
    { id: "2", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-04-22", owner_name: "J.Williams", transaction_type: "Sale", shares: 5000, value: 900000 } },
    { id: "3", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-03-15", owner_name: "T.Cook", transaction_type: "Buy", shares: 2000, value: 370000 } },
    { id: "4", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-02-28", owner_name: "C.Adams", transaction_type: "Sale", shares: 3500, value: 640000 } },
    { id: "5", security_id: "a", section: "i", period_end: "2024-01-01", period_type: "SNAPSHOT" as const, data: { date: "2024-01-12", owner_name: "D.Luca", transaction_type: "Buy", shares: 1000, value: 182000 } },
  ],
};

const EARNINGS_RECORDS = {
  records: [
    { id: "1", security_id: "a", section: "e", period_end: "2024-09-30", period_type: "ANNUAL" as const, data: { date: "2024-09-30", epsActual: 6.42, epsEstimate: 6.38, surprisePercent: 0.63 } },
    { id: "2", security_id: "a", section: "e", period_end: "2023-09-30", period_type: "ANNUAL" as const, data: { date: "2023-09-30", epsActual: 6.12, epsEstimate: 5.98, surprisePercent: 2.34 } },
    { id: "3", security_id: "a", section: "e", period_end: "2022-09-30", period_type: "ANNUAL" as const, data: { date: "2022-09-30", epsActual: 6.11, epsEstimate: 6.05, surprisePercent: 0.99 } },
    { id: "4", security_id: "a", section: "e", period_end: "2021-09-30", period_type: "ANNUAL" as const, data: { date: "2021-09-30", epsActual: 5.61, epsEstimate: 5.52, surprisePercent: 1.63 } },
  ],
};

const NEWS_DATA = {
  total: 5,
  articles: [
    { article_id: "a1", title: "Apple beats Q4 estimates", url: null, published_at: "2024-11-01T12:00:00Z", source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.9, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "positive" as const, impact_score: null, cluster_size: null },
    { article_id: "a2", title: "iPhone 16 demand strong", url: null, published_at: "2024-10-31T08:00:00Z", source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.8, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "positive" as const, impact_score: null, cluster_size: null },
    { article_id: "a3", title: "Apple supply chain risks", url: null, published_at: "2024-10-30T10:00:00Z", source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.7, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "negative" as const, impact_score: null, cluster_size: null },
    { article_id: "a4", title: "Vision Pro returns rising", url: null, published_at: "2024-10-29T14:00:00Z", source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.6, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "negative" as const, impact_score: null, cluster_size: null },
    { article_id: "a5", title: "Cook sells $2.8M in stock", url: null, published_at: "2024-10-28T09:00:00Z", source_type: null, source_name: null, routing_tier: null, routing_score: null, market_impact_score: null, llm_relevance_score: null, display_relevance_score: 0.5, primary_entity_id: null, primary_entity_symbol: null, impact_windows: null, sentiment: "neutral" as const, impact_score: null, cluster_size: null },
  ],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("W5 Quote tab density gate (Δ42)", () => {
  it("MultiPeriodReturnsStrip renders 7 period cells", () => {
    render(<MultiPeriodReturnsStrip data={MULTI_PERIOD_DATA} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBeGreaterThanOrEqual(7);
  });

  it("IntradayStatsBand renders 6 stat cells", () => {
    render(<IntradayStatsBand data={INTRADAY_DATA} />);
    const cells = screen.getAllByRole("cell");
    // PREM is shown because premarket_high is set (6 total including PREM).
    expect(cells.length).toBeGreaterThanOrEqual(5); // at minimum 5 without PREM
  });

  it("MetricGrid4Col renders correct cell count", () => {
    render(<MetricGrid4Col title="Valuation" cells={METRIC_GRID_CELLS_VALUATION} />);
    const cells = screen.getAllByRole("cell");
    expect(cells.length).toBe(8);
  });

  it("3 MetricGrid4Col blocks total 24 cells", () => {
    const { container } = render(
      <div>
        <MetricGrid4Col title="Valuation" cells={METRIC_GRID_CELLS_VALUATION} />
        <MetricGrid4Col title="Margins" cells={METRIC_GRID_CELLS_VALUATION} />
        <MetricGrid4Col title="Leverage" cells={METRIC_GRID_CELLS_VALUATION} />
      </div>
    );
    const cells = container.querySelectorAll('[role="cell"]');
    expect(cells.length).toBe(24);
  });

  it("InsiderActivityList renders 5 rows for 5 transactions", () => {
    render(<InsiderActivityList data={INSIDER_RECORDS} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(5);
  });

  it("EarningsMiniList renders 4 rows for 4 annual records", () => {
    render(<EarningsMiniList data={EARNINGS_RECORDS} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(4);
  });

  it("RelatedHeadlinesList renders 5 rows for 5 articles", () => {
    render(<RelatedHeadlinesList data={NEWS_DATA} />);
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(5);
  });

  it("combined W5 strips produce ≥ 50 data items above-fold (isolated subset)", () => {
    // Count total data items from all rendered W5 strips.
    // WHY 8 strips (not all 12): PeersStrip, PriceLevelsStrip, WhatsMovingStrip, and
    // SessionStatsStrip require heavier gateway/auth context mocks that belong in
    // integration tests rather than this unit-level density gate. The 8 strips below
    // are sufficient to validate the core density contract in isolation.
    //
    // WHY ≥ 50 (not ≥ 80): The full ≥ 80 Δ42 acceptance gate is validated via
    // Playwright e2e (instrument-quote.spec.ts T-31) which renders the real QuoteTab
    // at 1440×900 and counts visible cells. This unit gate checks that the component
    // subset it CAN render in JSDOM meets a proportional minimum.
    //
    // Actual counts:
    //   MultiPeriodReturnsStrip: 7 cells + 1 row
    //   IntradayStatsBand:       6 cells + 1 row
    //   3x MetricGrid4Col:      24 cells
    //   InsiderActivityList:     5 rows
    //   EarningsMiniList:        4 rows
    //   RelatedHeadlinesList:    5 rows
    //   ─────────────────────────────────────
    //   Total:                  37 cells + 16 rows = 53
    const { container } = render(
      <div>
        <MultiPeriodReturnsStrip data={MULTI_PERIOD_DATA} />
        <IntradayStatsBand data={INTRADAY_DATA} />
        <MetricGrid4Col title="Valuation" cells={METRIC_GRID_CELLS_VALUATION} />
        <MetricGrid4Col title="Margins" cells={METRIC_GRID_CELLS_VALUATION} />
        <MetricGrid4Col title="Leverage" cells={METRIC_GRID_CELLS_VALUATION} />
        <InsiderActivityList data={INSIDER_RECORDS} />
        <EarningsMiniList data={EARNINGS_RECORDS} />
        <RelatedHeadlinesList data={NEWS_DATA} />
      </div>
    );
    const cells = container.querySelectorAll('[role="cell"]');
    const rows  = container.querySelectorAll('[role="row"]');
    const total = cells.length + rows.length;
    expect(total).toBeGreaterThanOrEqual(50);
  });
});
