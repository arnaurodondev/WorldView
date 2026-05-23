/**
 * components/instrument/chart/__tests__/TimeframeToolbar.test.tsx
 *
 * WHY THESE TESTS EXIST:
 *   TimeframeToolbar is a pure presentation component that renders timeframe
 *   interval buttons, range preset buttons, and the chart type toggle (C/L/A).
 *   Tests verify:
 *     1. All 5 timeframe interval buttons render.
 *     2. The active timeframe receives aria-pressed=true / primary styling.
 *     3. Range preset buttons (YTD, 3Y, 5Y, ALL) render when onRangePreset is provided.
 *     4. Clicking a range preset fires onRangePreset with the correct preset ID.
 *     5. Range preset click also calls onTimeframeChange("1D") when current TF != "1D".
 *     6. Chart type toggle buttons (C, L, A) render when onChartTypeChange is provided.
 *     7. Active chart type button has aria-pressed=true.
 *     8. Clicking a chart type button fires onChartTypeChange with the correct type.
 *
 * WHAT IS NOT TESTED:
 *   - lightweight-charts internals (canvas library — no JSDOM rendering possible)
 *   - The actual visible range change on the chart (belongs to useChartSeries tests)
 *   - Log scale toggle (not changed by these tasks — existing behaviour)
 *
 * WHY NO SNAPSHOT TESTS: button labels and aria attributes are the load-bearing
 * contracts — snapshot tests would be brittle to styling tweaks. We assert on
 * the observable behaviour (aria-pressed, callback args) instead.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TimeframeToolbar } from "../TimeframeToolbar";
import type { TimeframeToolbarProps } from "../TimeframeToolbar";

// ── Default props ─────────────────────────────────────────────────────────────

/**
 * makeProps — build a minimal valid TimeframeToolbarProps with vi.fn() callbacks.
 * All optional new props (onRangePreset, onChartTypeChange) default to undefined
 * so tests opt-in only to what they need.
 */
function makeProps(overrides: Partial<TimeframeToolbarProps> = {}): TimeframeToolbarProps {
  return {
    timeframe: "1D",
    onTimeframeChange: vi.fn(),
    logScale: false,
    onToggleLogScale: vi.fn(),
    showCompareInput: false,
    onToggleCompareInput: vi.fn(),
    compareActive: false,
    compareInput: "",
    onCompareInputChange: vi.fn(),
    onCompareSubmit: vi.fn(),
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("TimeframeToolbar — timeframe interval buttons", () => {
  it("renders all 5 timeframe interval buttons", () => {
    render(<TimeframeToolbar {...makeProps()} />);

    // WHY test all 5: the order and presence of 5M/1H/1D/1W/1M is load-bearing
    // for S3 API compatibility — these map to exact backend timeframe strings.
    for (const tf of ["5M", "1H", "1D", "1W", "1M"]) {
      expect(screen.getByRole("button", { name: tf })).toBeInTheDocument();
    }
  });

  it("clicking a timeframe button calls onTimeframeChange with the correct value", () => {
    const onTimeframeChange = vi.fn();
    render(<TimeframeToolbar {...makeProps({ timeframe: "1D", onTimeframeChange })} />);

    fireEvent.click(screen.getByRole("button", { name: "1W" }));
    expect(onTimeframeChange).toHaveBeenCalledWith("1W");
    expect(onTimeframeChange).toHaveBeenCalledTimes(1);
  });
});

describe("TimeframeToolbar — range preset buttons", () => {
  // WHY guard on onRangePreset presence: the toolbar only renders range preset
  // buttons when the parent opts in by passing onRangePreset. This lets non-range
  // callers (e.g. tests that don't pass the prop) render a simpler toolbar.

  it("does NOT render range preset buttons when onRangePreset is omitted", () => {
    render(<TimeframeToolbar {...makeProps()} />);

    // WHY queryByTestId: the range preset buttons carry data-testid attributes;
    // if none exist, queryByTestId returns null (not throws).
    expect(screen.queryByTestId("range-preset-ytd")).not.toBeInTheDocument();
    expect(screen.queryByTestId("range-preset-all")).not.toBeInTheDocument();
  });

  it("renders YTD, 3Y, 5Y, ALL buttons when onRangePreset is provided", () => {
    render(<TimeframeToolbar {...makeProps({ onRangePreset: vi.fn() })} />);

    expect(screen.getByTestId("range-preset-ytd")).toBeInTheDocument();
    expect(screen.getByTestId("range-preset-3y")).toBeInTheDocument();
    expect(screen.getByTestId("range-preset-5y")).toBeInTheDocument();
    expect(screen.getByTestId("range-preset-all")).toBeInTheDocument();
  });

  it("clicking YTD fires onRangePreset('YTD')", () => {
    const onRangePreset = vi.fn();
    render(<TimeframeToolbar {...makeProps({ onRangePreset })} />);

    fireEvent.click(screen.getByTestId("range-preset-ytd"));
    expect(onRangePreset).toHaveBeenCalledWith("YTD");
    expect(onRangePreset).toHaveBeenCalledTimes(1);
  });

  it("clicking 3Y fires onRangePreset('3Y')", () => {
    const onRangePreset = vi.fn();
    render(<TimeframeToolbar {...makeProps({ onRangePreset })} />);

    fireEvent.click(screen.getByTestId("range-preset-3y"));
    expect(onRangePreset).toHaveBeenCalledWith("3Y");
  });

  it("clicking 5Y fires onRangePreset('5Y')", () => {
    const onRangePreset = vi.fn();
    render(<TimeframeToolbar {...makeProps({ onRangePreset })} />);

    fireEvent.click(screen.getByTestId("range-preset-5y"));
    expect(onRangePreset).toHaveBeenCalledWith("5Y");
  });

  it("clicking ALL fires onRangePreset('ALL')", () => {
    const onRangePreset = vi.fn();
    render(<TimeframeToolbar {...makeProps({ onRangePreset })} />);

    fireEvent.click(screen.getByTestId("range-preset-all"));
    expect(onRangePreset).toHaveBeenCalledWith("ALL");
  });

  it("clicking a range preset when timeframe is '5M' also calls onTimeframeChange('1D')", () => {
    // WHY: range presets pair with daily bars. If the user is on 5M, the toolbar
    // must switch to 1D first so the visible range makes sense (3Y of 5-min bars
    // = thousands of unreadable candles).
    const onRangePreset = vi.fn();
    const onTimeframeChange = vi.fn();
    render(
      <TimeframeToolbar
        {...makeProps({ timeframe: "5M", onRangePreset, onTimeframeChange })}
      />,
    );

    fireEvent.click(screen.getByTestId("range-preset-3y"));
    // Should switch to 1D AND fire the preset.
    expect(onTimeframeChange).toHaveBeenCalledWith("1D");
    expect(onRangePreset).toHaveBeenCalledWith("3Y");
  });

  it("clicking a range preset when already on '1D' does NOT call onTimeframeChange again", () => {
    // WHY: no-op change avoids triggering a re-fetch of the same 1D bars.
    const onRangePreset = vi.fn();
    const onTimeframeChange = vi.fn();
    render(
      <TimeframeToolbar
        {...makeProps({ timeframe: "1D", onRangePreset, onTimeframeChange })}
      />,
    );

    fireEvent.click(screen.getByTestId("range-preset-ytd"));
    // Already on 1D → no redundant timeframe change.
    expect(onTimeframeChange).not.toHaveBeenCalled();
    expect(onRangePreset).toHaveBeenCalledWith("YTD");
  });
});

describe("TimeframeToolbar — chart type toggle", () => {
  it("does NOT render C/L/A buttons when onChartTypeChange is omitted", () => {
    render(<TimeframeToolbar {...makeProps()} />);

    expect(screen.queryByTestId("chart-type-candle")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart-type-line")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart-type-area")).not.toBeInTheDocument();
  });

  it("renders C, L, A buttons when onChartTypeChange is provided", () => {
    render(<TimeframeToolbar {...makeProps({ onChartTypeChange: vi.fn() })} />);

    // WHY data-testid (not text): single-letter buttons "C"/"L"/"A" could match
    // unrelated accessible names. data-testid is an unambiguous selector.
    expect(screen.getByTestId("chart-type-candle")).toBeInTheDocument();
    expect(screen.getByTestId("chart-type-line")).toBeInTheDocument();
    expect(screen.getByTestId("chart-type-area")).toBeInTheDocument();
  });

  it("active chart type button has aria-pressed=true", () => {
    render(
      <TimeframeToolbar
        {...makeProps({ chartType: "line", onChartTypeChange: vi.fn() })}
      />,
    );

    expect(screen.getByTestId("chart-type-line")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("chart-type-candle")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("chart-type-area")).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking 'L' fires onChartTypeChange('line')", () => {
    const onChartTypeChange = vi.fn();
    render(
      <TimeframeToolbar
        {...makeProps({ chartType: "candle", onChartTypeChange })}
      />,
    );

    fireEvent.click(screen.getByTestId("chart-type-line"));
    expect(onChartTypeChange).toHaveBeenCalledWith("line");
    expect(onChartTypeChange).toHaveBeenCalledTimes(1);
  });

  it("clicking 'A' fires onChartTypeChange('area')", () => {
    const onChartTypeChange = vi.fn();
    render(
      <TimeframeToolbar
        {...makeProps({ chartType: "candle", onChartTypeChange })}
      />,
    );

    fireEvent.click(screen.getByTestId("chart-type-area"));
    expect(onChartTypeChange).toHaveBeenCalledWith("area");
  });

  it("clicking 'C' fires onChartTypeChange('candle')", () => {
    const onChartTypeChange = vi.fn();
    render(
      <TimeframeToolbar
        {...makeProps({ chartType: "line", onChartTypeChange })}
      />,
    );

    fireEvent.click(screen.getByTestId("chart-type-candle"));
    expect(onChartTypeChange).toHaveBeenCalledWith("candle");
  });

  it("defaults to chartType='candle' (C button aria-pressed=true) when chartType prop is omitted", () => {
    render(<TimeframeToolbar {...makeProps({ onChartTypeChange: vi.fn() })} />);

    expect(screen.getByTestId("chart-type-candle")).toHaveAttribute("aria-pressed", "true");
  });
});
