/**
 * components/instrument/financials/__tests__/DenseMetricsGrid.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 3): pins the dense grid's
 * two structural guarantees:
 *   1. With ALL data null, every cell still renders an explicit "—" marker —
 *      no blank cells (the no-blank-areas rule).
 *   2. Section headers render with the left accent bar (border-l-primary)
 *      that makes section starts scannable.
 */

import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { DenseMetricsGrid } from "@/components/instrument/financials/DenseMetricsGrid";

afterEach(() => cleanup());

function renderEmptyGrid() {
  return render(
    <DenseMetricsGrid
      fundamentals={null}
      snapshot={null}
      technicals={null}
      shareStats={null}
      dividends={null}
    />,
  );
}

describe("DenseMetricsGrid named null states", () => {
  it("renders an explicit '—' for every metric when all data is null", () => {
    renderEmptyGrid();
    // 39 metric cells; with everything null each value cell shows the dash.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(30);
  });

  it("renders all 8 section headers", () => {
    renderEmptyGrid();
    for (const label of [
      "VALUATION",
      "PROFITABILITY",
      "GROWTH",
      "BALANCE SHEET",
      "CASH FLOW",
      "DIVIDENDS",
      "OWNERSHIP",
      "TECHNICALS",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

describe("DenseMetricsGrid section header accent bar (Round-1)", () => {
  it("every section header carries the left primary accent bar", () => {
    const { container } = renderEmptyGrid();
    const headers = container.querySelectorAll("[data-metric-section]");
    expect(headers.length).toBe(8);
    for (const header of Array.from(headers)) {
      // WHY class assertions: the 2px yellow accent is the visual section
      // delimiter; losing border-l-primary silently flattens the hierarchy.
      expect(header.className).toContain("border-l-2");
      expect(header.className).toContain("border-l-primary");
    }
  });
});
