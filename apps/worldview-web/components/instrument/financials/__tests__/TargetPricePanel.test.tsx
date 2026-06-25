/**
 * TargetPricePanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the target price display contract — section header,
 * formatted price, upside chip direction, and graceful null handling.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TargetPricePanel } from "@/components/instrument/financials/sidebar/TargetPricePanel";

describe("TargetPricePanel", () => {
  it("renders section header", () => {
    render(<TargetPricePanel targetPrice={215.0} currentPrice={190.0} updatedAt={null} />);
    expect(screen.getByText("12-MO TARGET")).toBeInTheDocument();
  });

  it("renders formatted target price", () => {
    render(<TargetPricePanel targetPrice={215.5} currentPrice={190.0} updatedAt={null} />);
    // price should appear as formatted text
    expect(screen.getByText(/215/)).toBeInTheDocument();
  });

  it("renders upside chip with ▲ when target is above current", () => {
    render(<TargetPricePanel targetPrice={215.0} currentPrice={190.0} updatedAt={null} />);
    // upside = (215-190)/190 ≈ 13.2% → ▲ chip
    expect(screen.getByText(/▲/)).toBeInTheDocument();
  });

  it("renders downside chip with ▼ when target is below current", () => {
    render(<TargetPricePanel targetPrice={170.0} currentPrice={190.0} updatedAt={null} />);
    // downside → ▼ chip
    expect(screen.getByText(/▼/)).toBeInTheDocument();
  });

  it("renders — when targetPrice is null", () => {
    render(<TargetPricePanel targetPrice={null} currentPrice={190.0} updatedAt={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("hides upside chip when currentPrice is null", () => {
    render(<TargetPricePanel targetPrice={215.0} currentPrice={null} updatedAt={null} />);
    // no upside calculation possible → no chip
    expect(screen.queryByText(/▲/)).toBeNull();
    expect(screen.queryByText(/▼/)).toBeNull();
  });
});

// ── Round-1 Foundation: current → target bar ─────────────────────────────────
// WHY these tests: requirement 3 — the bar must render for ANY non-null price
// pair, including the single-analyst case where target == current (the
// min==max scale previously implied a divide-by-zero → NaN% widths).
describe("TargetPricePanel target bar (Round-1)", () => {
  it("renders the bar when both prices are present", () => {
    render(<TargetPricePanel targetPrice={215.0} currentPrice={190.0} updatedAt={null} />);
    expect(screen.getByTestId("target-price-bar")).toBeInTheDocument();
  });

  it("renders the bar without NaN positions when target equals current (min==max guard)", () => {
    render(<TargetPricePanel targetPrice={190.0} currentPrice={190.0} updatedAt={null} />);
    const bar = screen.getByTestId("target-price-bar");
    expect(bar).toBeInTheDocument();
    // Every positioned child must carry a finite percentage — "NaN%" is the
    // failure signature of an unguarded (v - lo) / (hi - lo) scale.
    for (const child of Array.from(bar.children)) {
      const style = (child as HTMLElement).getAttribute("style") ?? "";
      expect(style).not.toContain("NaN");
    }
  });

  it("hides the bar when currentPrice is missing (one point carries no information)", () => {
    render(<TargetPricePanel targetPrice={215.0} currentPrice={null} updatedAt={null} />);
    expect(screen.queryByTestId("target-price-bar")).toBeNull();
  });

  it("hides the bar when targetPrice is missing", () => {
    render(<TargetPricePanel targetPrice={null} currentPrice={190.0} updatedAt={null} />);
    expect(screen.queryByTestId("target-price-bar")).toBeNull();
  });
});
