/**
 * features/portfolio/components/__tests__/HoldingsTabSectorFilter.test.tsx (R2)
 *
 * WHY: the donut-driven sector filter changes WHICH rows (and which TOTAL)
 * the holdings table receives — a money-facing path. These tests pin:
 *   1. No filter → all rows pass through, no chip, kpi.totalValue intact.
 *   2. Filter → only matching rows reach the table, the pinned-TOTAL value
 *      is recomputed from the VISIBLE rows, chip + "n of m" render.
 *   3. Chip × dismisses via the page callback.
 *   4. A filter matching nothing renders the named no-match state (NOT the
 *      misleading "connect a brokerage" empty state).
 *
 * MOCKED: every heavy child (AG Grid table, lightweight-charts panel, data
 * strips) — this test is about HoldingsTab's filtering/derivation logic,
 * not the children's rendering. SemanticHoldingsTable's mock echoes the
 * props it receives so assertions read them from the DOM.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import type { Holding, HoldingsResponse } from "@/types/api";
import type { PortfolioKPI } from "@/features/portfolio/lib/kpi";

// ── Heavy-child mocks ─────────────────────────────────────────────────────────

// SemanticHoldingsTable mock: echoes received tickers + totalValue.
vi.mock("@/components/portfolio/SemanticHoldingsTable", () => ({
  SemanticHoldingsTable: ({
    holdings,
    totalValue,
  }: {
    holdings: Holding[];
    totalValue: number;
  }) => (
    <div data-testid="mock-holdings-table" data-total={totalValue}>
      {holdings.map((h) => h.ticker).join(",")}
    </div>
  ),
}));
vi.mock("@/components/portfolio/ExposureCurrencyStrip", () => ({
  ExposureCurrencyStrip: () => <div />,
}));
vi.mock("@/components/portfolio/ConcentrationSectorTeaseStrip", () => ({
  ConcentrationSectorTeaseStrip: () => <div />,
}));
vi.mock("@/components/portfolio/PerformanceChartPanel", () => ({
  PerformanceChartPanel: () => <div />,
}));
vi.mock("@/components/portfolio/SectorAllocationBar", () => ({
  SectorAllocationBar: () => <div />,
}));
// Chrome mock keeps positionCount visible for the "count reflects filter" assert.
vi.mock("@/components/portfolio/HoldingsTableChrome", () => ({
  HoldingsTableChrome: ({ positionCount }: { positionCount: number }) => (
    <div data-testid="mock-chrome">{positionCount} positions</div>
  ),
}));
vi.mock("@/components/portfolio/BottomStripCluster", () => ({
  BottomStripCluster: () => <div />,
}));
vi.mock("@/components/portfolio/detail/HoldingDetailSlideOver", () => ({
  HoldingDetailSlideOver: () => <div />,
}));
vi.mock("@/features/portfolio/hooks/useHoldingsSeries", () => ({
  useHoldingsSeries: () => ({ series: {} }),
}));
vi.mock("@/features/portfolio/hooks/useTopMovers", () => ({
  useTopMovers: () => ({ contributors: [], detractors: [] }),
}));

// ── SUT import (after mocks) ─────────────────────────────────────────────────
import { HoldingsTab } from "../HoldingsTab";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeHolding(id: string, ticker: string, qty: number, cost: number): Holding {
  return {
    holding_id: `h-${id}`,
    portfolio_id: "p-1",
    instrument_id: id,
    entity_id: `e-${id}`,
    ticker,
    name: ticker,
    quantity: qty,
    average_cost: cost,
    current_price: null,
    unrealised_pnl: null,
    unrealised_pnl_pct: null,
    portfolio_weight: null,
  };
}

const HOLDINGS = [
  makeHolding("i-aapl", "AAPL", 10, 150), // Technology
  makeHolding("i-xom", "XOM", 20, 100), // Energy
];

// Live quotes: AAPL $200 → $2,000 position; XOM $110 → $2,200 position.
// Full Quote shape — the prop type is BatchQuoteResponse["quotes"].
const QUOTES = {
  "i-aapl": {
    instrument_id: "i-aapl",
    ticker: "AAPL",
    price: 200,
    change: 1,
    change_pct: 0.5,
    timestamp: "2026-06-10T15:00:00Z",
    volume: 1_000_000,
  },
  "i-xom": {
    instrument_id: "i-xom",
    ticker: "XOM",
    price: 110,
    change: -1,
    change_pct: -0.9,
    timestamp: "2026-06-10T15:00:00Z",
    volume: 2_000_000,
  },
};

// Overviews provide each holding's sector (the filter's data source).
const OVERVIEWS = {
  "i-aapl": { sector: "Technology" },
  "i-xom": { sector: "Energy" },
  // Cast: the real HoldingOverviewMap has many more fields; only `sector`
  // is read by the code under test.
} as never;

const KPI: PortfolioKPI = {
  totalValue: 4_200, // 2,000 + 2,200
  dayPnl: 0,
  unrealisedPnl: 0,
  unrealisedPnlPct: 0,
  topGainer: null,
  topLoser: null,
  positionCount: 2,
  realizedPnl: null,
};

const HOLDINGS_RESP: HoldingsResponse = {
  portfolio_id: "p-1",
  holdings: HOLDINGS,
  total_value: null,
  total_cost: null,
  total_unrealised_pnl: null,
  total_unrealised_pnl_pct: null,
};

function renderTab(
  sectorFilter: string | null,
  onClearSectorFilter = vi.fn(),
) {
  render(
    <HoldingsTab
      activePortfolioId="p-1"
      holdingsLoading={false}
      holdingsResp={HOLDINGS_RESP}
      enrichedHoldings={HOLDINGS}
      holdingsQuotes={QUOTES}
      holdingOverviews={OVERVIEWS}
      kpi={KPI}
      bySector={[]}
      byType={[]}
      equityPeriod="3M"
      setEquityPeriod={vi.fn()}
      sectorFilter={sectorFilter}
      onClearSectorFilter={onClearSectorFilter}
    />,
  );
  return { onClearSectorFilter };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingsTab sector filter (R2)", () => {
  it("no filter: all rows pass through, no chip, full-book total", () => {
    renderTab(null);

    const table = screen.getByTestId("mock-holdings-table");
    expect(table).toHaveTextContent("AAPL,XOM");
    // Unfiltered total = kpi.totalValue untouched.
    expect(table).toHaveAttribute("data-total", "4200");
    expect(screen.queryByTestId("sector-filter-chip-row")).not.toBeInTheDocument();
    expect(screen.getByTestId("mock-chrome")).toHaveTextContent("2 positions");
  });

  it("filter: only matching rows, recomputed total, chip + n-of-m", () => {
    renderTab("Technology");

    const table = screen.getByTestId("mock-holdings-table");
    // Only the Technology holding survives.
    expect(table).toHaveTextContent("AAPL");
    expect(table).not.toHaveTextContent("XOM");
    // TOTAL row value recomputed from VISIBLE rows: 10 × $200 = $2,000 —
    // NOT the whole-book 4,200, which would contradict the rows shown.
    expect(table).toHaveAttribute("data-total", "2000");

    // Dismissible chip + honest n-of-m count.
    expect(screen.getByTestId("sector-filter-chip")).toHaveTextContent("Technology");
    expect(screen.getByText("1 of 2 positions")).toBeInTheDocument();
    expect(screen.getByTestId("mock-chrome")).toHaveTextContent("1 positions");
  });

  it("chip × clears via the page callback", () => {
    const { onClearSectorFilter } = renderTab("Energy");
    fireEvent.click(screen.getByTestId("sector-filter-chip"));
    expect(onClearSectorFilter).toHaveBeenCalledOnce();
  });

  it("filter matching nothing renders the named no-match state (not the brokerage empty state)", () => {
    renderTab("Utilities");
    expect(screen.getByTestId("sector-filter-no-match")).toHaveTextContent(
      /No holdings in .Utilities./,
    );
    // The table (and its "connect a brokerage" empty state) is NOT rendered.
    expect(screen.queryByTestId("mock-holdings-table")).not.toBeInTheDocument();
    // The chip row is still present so the user can clear the filter.
    expect(screen.getByTestId("sector-filter-chip")).toBeInTheDocument();
  });

  // R3 polish: the no-match state gained an inline "Clear filter" action so
  // the exit path is one keyboard-reachable click inside the state itself
  // (EmptyState action-slot parity — DS §15.12), not only the chip above.
  it("no-match state exposes a Clear filter action wired to the page callback", () => {
    const { onClearSectorFilter } = renderTab("Utilities");
    fireEvent.click(screen.getByTestId("sector-filter-no-match-clear"));
    expect(onClearSectorFilter).toHaveBeenCalledOnce();
  });
});
