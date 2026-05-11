/**
 * __tests__/portfolio-kpi-strip.test.tsx — Unit tests for PortfolioKPIStrip
 *
 * WHY THIS EXISTS (PLAN-0051 T-A-1-07): the Realized P&L tile gained two
 * new presentation modes (FIFO server value vs client-side approximation
 * with "(approx)" badge). These tests pin both rendering paths so we don't
 * silently regress to displaying the approximation as the FIFO value.
 *
 * Why a new file (not extending portfolio.test.tsx): the existing
 * portfolio.test focuses on tab-switching. This file focuses solely on
 * the KPI strip presentation contract — easier to find, easier to extend
 * when the strip grows new tiles.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";

// Minimal happy-path props the tests can spread + override.
const baseProps = {
  totalValue: 100_000,
  dayPnl: 0,
  unrealisedPnl: 0,
  unrealisedPnlPct: 0,
  topGainer: null,
  topLoser: null,
  positionCount: 0,
};

describe("PortfolioKPIStrip — Realized P&L tile", () => {
  it("renders the Realized P&L label and value when provided", () => {
    render(<PortfolioKPIStrip {...baseProps} realizedPnl={1234} />);
    // Label
    expect(screen.getByText("Realized P&L")).toBeInTheDocument();
    // Value tile carries the data-testid for stable querying.
    const tile = screen.getByTestId("kpi-realized-pnl");
    expect(tile.textContent).toContain("1,234");
  });

  it("applies text-positive class when value is positive", () => {
    render(<PortfolioKPIStrip {...baseProps} realizedPnl={500} />);
    const tile = screen.getByTestId("kpi-realized-pnl");
    // The value <span> inherits the color class from the parent tile;
    // we look at the inner span explicitly.
    expect(tile.innerHTML).toContain("text-positive");
  });

  it("applies text-negative class when value is negative", () => {
    render(<PortfolioKPIStrip {...baseProps} realizedPnl={-200} />);
    const tile = screen.getByTestId("kpi-realized-pnl");
    expect(tile.innerHTML).toContain("text-negative");
  });

  it("renders em-dash when realizedPnl is null", () => {
    render(<PortfolioKPIStrip {...baseProps} realizedPnl={null} />);
    const tile = screen.getByTestId("kpi-realized-pnl");
    expect(tile.textContent).toContain("—");
  });

  it("shows the (approx) suffix when realizedPnlApprox=true", () => {
    render(
      <PortfolioKPIStrip
        {...baseProps}
        realizedPnl={500}
        realizedPnlApprox
      />,
    );
    const tile = screen.getByTestId("kpi-realized-pnl");
    expect(tile.textContent).toContain("(approx)");
    // Tooltip explains the degradation
    expect(tile.getAttribute("title")).toContain("Backend unavailable");
  });

  it("hides the (approx) suffix when FIFO endpoint succeeded", () => {
    render(
      <PortfolioKPIStrip
        {...baseProps}
        realizedPnl={500}
        realizedPnlApprox={false}
        realizedPnlLongTerm={300}
        realizedPnlShortTerm={200}
      />,
    );
    const tile = screen.getByTestId("kpi-realized-pnl");
    expect(tile.textContent).not.toContain("(approx)");
    // Tooltip surfaces long/short-term breakdown
    const title = tile.getAttribute("title") ?? "";
    expect(title).toContain("Long-term");
    expect(title).toContain("Short-term");
  });
});
