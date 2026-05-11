/**
 * __tests__/screener-mini-chart.test.tsx — MiniChart sparkline rendering
 *
 * WHY THIS EXISTS: MiniChart is shared across every screener row. A regression
 * here (wrong colour direction, empty-state crash, axis flip) corrupts visual
 * scanning across the whole table. These tests cover the three render paths:
 * positive trend, negative trend, and empty/insufficient data.
 *
 * WHY data-direction attribute: parsing inline SVG colour styles is brittle
 * across jsdom versions. The component exposes a stable data-direction
 * attribute we can assert without inspecting CSS.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MiniChart } from "@/components/screener/MiniChart";
import type { OHLCVBar } from "@/types/api";

function makeBars(closes: number[]): OHLCVBar[] {
  return closes.map((c, i) => ({
    timestamp: `2026-04-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
    open: c, high: c, low: c, close: c, volume: 0,
  }));
}

describe("MiniChart", () => {
  it("renders an SVG path when given >= 2 bars", () => {
    render(<MiniChart bars={makeBars([100, 105, 110])} />);
    const svg = screen.getByTestId("mini-chart");
    expect(svg).toBeInTheDocument();
    // SVG should contain a <path> element
    expect(svg.querySelector("path")).toBeInTheDocument();
  });

  it("uses positive direction when last close > first close", () => {
    render(<MiniChart bars={makeBars([100, 105, 110])} />);
    expect(screen.getByTestId("mini-chart")).toHaveAttribute("data-direction", "positive");
  });

  it("uses negative direction when last close < first close", () => {
    render(<MiniChart bars={makeBars([110, 105, 100])} />);
    expect(screen.getByTestId("mini-chart")).toHaveAttribute("data-direction", "negative");
  });

  it("uses flat direction when first and last close are equal", () => {
    render(<MiniChart bars={makeBars([100, 105, 100])} />);
    expect(screen.getByTestId("mini-chart")).toHaveAttribute("data-direction", "flat");
  });

  it("renders empty-state placeholder for null bars", () => {
    render(<MiniChart bars={null} />);
    expect(screen.getByTestId("mini-chart-empty")).toBeInTheDocument();
  });

  it("renders empty-state placeholder for empty array", () => {
    render(<MiniChart bars={[]} />);
    expect(screen.getByTestId("mini-chart-empty")).toBeInTheDocument();
  });

  it("renders empty-state placeholder for single bar (insufficient data)", () => {
    render(<MiniChart bars={makeBars([100])} />);
    expect(screen.getByTestId("mini-chart-empty")).toBeInTheDocument();
  });

  it("applies aria-label for accessibility", () => {
    render(<MiniChart bars={makeBars([100, 105])} ariaLabel="AAPL trend" />);
    expect(screen.getByLabelText("AAPL trend")).toBeInTheDocument();
  });
});
