/**
 * __tests__/probability-chart.test.tsx — ProbabilityChart states + interval
 * toggle (PLAN-0056 Wave E2, task 2).
 *
 * NOTE: recharts renders to SVG via ResponsiveContainer, which measures its
 * container. jsdom reports 0×0 so the <LineChart> paths don't paint — we
 * therefore assert on the component's STATE (loading/error/empty vs chart
 * present) and on the query switching, not on SVG geometry. The plotted numbers
 * are proven by prediction-markets-probability-series.test.ts.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PredictionMarketPricePoint } from "@/types/api";

// ── Mock the data hook so we control loading/error/data + capture the interval ─
const mockUseHistory = vi.fn();
vi.mock("@/lib/api/prediction-markets-hooks", () => ({
  usePredictionMarketPriceHistory: (conditionId: string, interval: string) =>
    mockUseHistory(conditionId, interval),
}));

import { ProbabilityChart } from "@/components/prediction-markets/ProbabilityChart";

function point(overrides: Partial<PredictionMarketPricePoint>): PredictionMarketPricePoint {
  return {
    window_start_ts: "2026-07-01T00:00:00Z",
    price: 0.6,
    interval: "1d",
    token_id: "tok-yes",
    outcome_name: "Yes",
    ...overrides,
  };
}

beforeEach(() => {
  mockUseHistory.mockReset();
});

describe("ProbabilityChart", () => {
  it("renders the chart (no empty/error/loading state) when history has points", () => {
    mockUseHistory.mockReturnValue({
      data: {
        market_id: "c1",
        interval: "1d",
        points: [point({}), point({ window_start_ts: "2026-07-02T00:00:00Z", price: 0.7 })],
      },
      isLoading: false,
      isError: false,
    });
    render(<ProbabilityChart conditionId="c1" />);
    expect(screen.getByTestId("probability-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("probability-chart-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("probability-chart-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("probability-chart-loading")).not.toBeInTheDocument();
  });

  it("renders the loading skeleton while pending", () => {
    mockUseHistory.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<ProbabilityChart conditionId="c1" />);
    expect(screen.getByTestId("probability-chart-loading")).toBeInTheDocument();
  });

  it("renders the error state on fetch failure", () => {
    mockUseHistory.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<ProbabilityChart conditionId="c1" />);
    expect(screen.getByTestId("probability-chart-error")).toBeInTheDocument();
  });

  it("renders the empty state when there are no points", () => {
    mockUseHistory.mockReturnValue({
      data: { market_id: "c1", interval: "1d", points: [] },
      isLoading: false,
      isError: false,
    });
    render(<ProbabilityChart conditionId="c1" />);
    expect(screen.getByTestId("probability-chart-empty")).toBeInTheDocument();
  });

  it("switches the query interval when a toggle is clicked", async () => {
    mockUseHistory.mockReturnValue({
      data: { market_id: "c1", interval: "1d", points: [] },
      isLoading: false,
      isError: false,
    });
    const onIntervalChange = vi.fn();
    const user = userEvent.setup();
    render(<ProbabilityChart conditionId="c1" onIntervalChange={onIntervalChange} />);

    // Initial render queries the default "1d".
    expect(mockUseHistory).toHaveBeenCalledWith("c1", "1d");

    // Click the "1h" tab → hook re-queries with "1h" and parent is notified.
    // WHY userEvent (not fireEvent.click): Radix Tabs activates on the full
    // pointerdown→click sequence, which fireEvent.click alone doesn't emit.
    await user.click(screen.getByRole("tab", { name: "1h" }));
    expect(mockUseHistory).toHaveBeenCalledWith("c1", "1h");
    expect(onIntervalChange).toHaveBeenCalledWith("1h");
  });
});
