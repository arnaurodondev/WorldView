/**
 * components/portfolio/__tests__/PortfolioLoadingSkeleton.test.tsx —
 * PLAN-0122 W-B (T-A-B-02): the loading skeleton must mirror the ACTIVE mode's
 * above-fold shape so the first paint matches the resolved data (no layout jump).
 *
 * WHY test the extracted component (not the whole page): the page skeleton path
 * requires the full usePortfolioData + auth + bundle mock harness; the shape logic
 * is pure and worth pinning directly here.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioLoadingSkeleton } from "@/components/portfolio/PortfolioLoadingSkeleton";

describe("PortfolioLoadingSkeleton (PLAN-0122 W-B)", () => {
  it("test_skeleton_simple_four_tiles_no_donut", () => {
    render(<PortfolioLoadingSkeleton mode="simple" />);

    // Simple → the KPI-strip skeleton has exactly 4 tile placeholders…
    const strip = screen.getByTestId("kpi-strip-skeleton");
    expect(strip.children).toHaveLength(4);

    // …and NO donut placeholder (the donut is Advanced-only).
    expect(screen.queryByTestId("donut-skeleton")).not.toBeInTheDocument();
  });

  it("test_skeleton_advanced_eight_tiles_donut", () => {
    render(<PortfolioLoadingSkeleton mode="advanced" />);

    // Advanced → today's shape: 8 tile placeholders + the donut band placeholder.
    const strip = screen.getByTestId("kpi-strip-skeleton");
    expect(strip.children).toHaveLength(8);
    expect(screen.getByTestId("donut-skeleton")).toBeInTheDocument();
  });
});
