/**
 * components/instrument/chart/__tests__/CrosshairLegend.test.tsx
 *
 * WHY THIS EXISTS (Round-1 requirement 2c): pins the hovered-candle legend
 * contract — null bar renders NOTHING (canvas stays unobstructed), a bar
 * renders all five OHLC+V values with direction-coded close color.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CrosshairLegend } from "@/components/instrument/chart/CrosshairLegend";
import type { OHLCVBar } from "@/types/api";

const BAR: OHLCVBar = {
  timestamp: "2026-06-09T14:35:00Z",
  open: 100.5,
  high: 103.25,
  low: 99.75,
  close: 102.0,
  volume: 1_250_000,
};

describe("CrosshairLegend", () => {
  it("renders nothing when no bar is hovered", () => {
    const { container } = render(<CrosshairLegend bar={null} />);
    // WHY firstChild check: the component must return null — even an empty
    // wrapper div would float over the price axis and read as a glitch.
    expect(container.firstChild).toBeNull();
  });

  it("renders O/H/L/C and volume for the hovered bar", () => {
    render(<CrosshairLegend bar={BAR} />);
    expect(screen.getByTestId("crosshair-legend")).toBeInTheDocument();
    expect(screen.getByText("100.50")).toBeInTheDocument(); // O
    expect(screen.getByText("103.25")).toBeInTheDocument(); // H
    expect(screen.getByText("99.75")).toBeInTheDocument();  // L
    expect(screen.getByText("102.00")).toBeInTheDocument(); // C
    // Volume goes through formatVolume → compact "1.25M"-style notation.
    expect(screen.getByText(/1\.25?M/)).toBeInTheDocument();
  });

  it("colors the close teal for a bullish candle and red for bearish", () => {
    const { rerender } = render(<CrosshairLegend bar={BAR} />);
    // close (102) ≥ open (100.5) → bullish → text-positive.
    expect(screen.getByText("102.00").className).toContain("text-positive");

    rerender(<CrosshairLegend bar={{ ...BAR, close: 99.9 }} />);
    expect(screen.getByText("99.90").className).toContain("text-negative");
  });

  it("shows the bar's date+time so intraday candles are unambiguous", () => {
    render(<CrosshairLegend bar={BAR} />);
    expect(screen.getByText("2026-06-09 14:35")).toBeInTheDocument();
  });
});
