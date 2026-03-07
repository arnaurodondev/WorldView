import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { OHLCVChart } from "../src/components/OHLCVChart";

// Mock lightweight-charts since it requires a real DOM canvas
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addCandlestickSeries: vi.fn(() => ({
      setData: vi.fn(),
    })),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
    })),
    remove: vi.fn(),
  })),
}));

describe("OHLCVChart", () => {
  it("renders a chart container", () => {
    const mockData = [
      { date: "2025-01-01", open: 100, high: 110, low: 95, close: 105, volume: 1000 },
      { date: "2025-01-02", open: 105, high: 115, low: 100, close: 110, volume: 1200 },
    ];

    render(<OHLCVChart data={mockData} />);
    expect(screen.getByTestId("ohlcv-chart")).toBeInTheDocument();
  });

  it("renders with empty data", () => {
    render(<OHLCVChart data={[]} />);
    expect(screen.getByTestId("ohlcv-chart")).toBeInTheDocument();
  });
});
