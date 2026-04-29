/**
 * __tests__/chart-toolbar-wave-c.test.tsx — Wave C chart toolbar + indicator tests
 *
 * WHY THIS EXISTS: Covers the new Wave C features added in PLAN-0050:
 *   1. ChartToolbar — Indicators dropdown checkbox interactions
 *   2. ChartToolbar — Volume submenu checkbox interactions
 *   3. DrawingPalette — tool selection + arm/disarm model
 *   4. instrument-context — indicator computation functions (RSI, MACD, BB, ATR, STOCH, OBV, VWAP)
 *   5. instrument-context — localStorage persistence round-trip
 *   6. OHLCVChart — renders toolbar, timeframes, and drawing palette together
 *
 * WHY UNIT TESTS (not integration/e2e) for indicator math:
 *   Indicator computations are pure functions with no browser/network dependencies.
 *   Unit tests verify the math (correctness of Wilder's RSI smoothing, MACD EMA,
 *   Bollinger σ, etc.) without requiring a running chart or DOM.
 *
 * WHY mock lightweight-charts for OHLCVChart tests: lightweight-charts uses browser
 * Canvas/WebGL APIs unavailable in jsdom. The chart rendering is not the subject
 * of these tests — we verify toolbar interactions and state management.
 *
 * WHO USES IT: CI pre-merge gate; PLAN-0050 Wave C QA validation gate.
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-05
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { act } from "react";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ──────────────────────────────────────────────────────────────

// WHY mock lightweight-charts: WebGL APIs not available in jsdom.
// The mock returns enough surface for OHLCVChart to initialise without crashing.
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addCandlestickSeries: vi.fn(() => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    })),
    addHistogramSeries: vi.fn(() => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    })),
    addLineSeries: vi.fn(() => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    })),
    priceScale: vi.fn(() => ({
      applyOptions: vi.fn(),
    })),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
      timeToCoordinate: vi.fn(() => null),
      coordinateToTime: vi.fn(() => null),
    })),
    remove: vi.fn(),
  })),
}));

// WHY mock next/navigation: OHLCVChart → ChartToolbar doesn't directly use routing,
// but transitive imports (EntityGraphPanel etc.) may. Prevent module resolution errors.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY mock gateway: OHLCVChart calls createGateway(accessToken).getOHLCV().
// We want to control the response to test data-dependent indicator rendering.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getOHLCV: vi.fn().mockResolvedValue({
      instrument_id: "ins-001",
      ticker: "AAPL",
      timeframe: "1D",
      bars: generateTestBars(60), // 60 bars — enough for most indicators
    }),
    refreshToken: vi.fn().mockResolvedValue({ access_token: "tok", user: {}, expires_in: 900 }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// WHY mock useAuth: OHLCVChart uses accessToken to gate the query.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    logout: vi.fn(),
  })),
}));

// WHY mock indexedDB operations: jsdom doesn't implement IndexedDB reliably.
// We mock the persistence functions to be no-ops — this tests the UI interactions
// without being blocked by IndexedDB unavailability.
vi.mock("@/lib/instrument-context", async () => {
  const actual = await vi.importActual<typeof import("@/lib/instrument-context")>(
    "@/lib/instrument-context",
  );
  return {
    ...actual,
    // WHY mock only persistence functions: the computation functions (computeRSI, etc.)
    // are the subject of separate unit tests and should NOT be mocked there.
    // Here, we only mock the async IDB operations.
    loadAnnotationsFromIDB: vi.fn().mockResolvedValue([]),
    saveAnnotationsToIDB: vi.fn().mockResolvedValue(undefined),
    // WHY keep loadIndicatorsFromStorage: the function reads localStorage which IS
    // available in jsdom (via vitest's setup). Let it run normally.
  };
});

// ── Test helpers ──────────────────────────────────────────────────────────────

/**
 * generateTestBars — creates N synthetic OHLCV bars for indicator testing.
 *
 * WHY synthetic data (not real AAPL prices): tests should be deterministic and
 * reproducible. Real price data could make tests depend on external data validity.
 * Synthetic data with known structure allows verifying exact expected values.
 *
 * Bar pattern: price oscillates between 100 and 120 with volume proportional to
 * price movement. This creates both up and down candles for indicator testing.
 */
function generateTestBars(count: number) {
  const bars = [];
  let price = 100;
  const startTime = Math.floor(new Date("2026-01-01").getTime() / 1000);
  const DAY = 86400;
  for (let i = 0; i < count; i++) {
    const change = ((i % 7) - 3) * 0.5; // oscillating change
    price = Math.max(95, Math.min(125, price + change));
    bars.push({
      timestamp: new Date((startTime + i * DAY) * 1000).toISOString(),
      open: price - 0.5,
      high: price + 1,
      low: price - 1,
      close: price,
      volume: 1_000_000 + Math.abs(change) * 100_000,
    });
  }
  return bars;
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

// ── ChartToolbar unit tests ───────────────────────────────────────────────────

import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { createDefaultIndicatorState } from "@/lib/instrument-context";
import type { IndicatorId, IndicatorConfig } from "@/lib/instrument-context";

describe("ChartToolbar — Wave C", () => {
  let indicators: Record<IndicatorId, IndicatorConfig>;
  let onToggleIndicator: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    indicators = createDefaultIndicatorState();
    onToggleIndicator = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  function renderToolbar(overrides: Partial<Record<IndicatorId, IndicatorConfig>> = {}) {
    const merged = { ...indicators, ...overrides };
    return render(
      <ChartToolbar
        showVolume={true}
        onToggleVolume={vi.fn()}
        showMA50={false}
        onToggleMA50={vi.fn()}
        showMA200={false}
        onToggleMA200={vi.fn()}
        isFullscreen={false}
        onFullscreen={vi.fn()}
        indicators={merged}
        onToggleIndicator={onToggleIndicator}
        showVolMA20={false}
        onToggleVolMA20={vi.fn()}
        showVolProfile={false}
        onToggleVolProfile={vi.fn()}
        showVWAPLine={false}
        onToggleVWAPLine={vi.fn()}
      />,
    );
  }

  it("renders the indicators dropdown trigger button", () => {
    renderToolbar();
    // WHY data-testid (not text): the IND button label changes based on active count
    // ("IND" vs "IND 2"). Using data-testid makes the assertion selector stable.
    expect(screen.getByTestId("toolbar-indicators-menu")).toBeInTheDocument();
  });

  it("shows 'IND' label when no indicators active", () => {
    renderToolbar();
    expect(screen.getByTestId("toolbar-indicators-menu")).toHaveTextContent("IND");
  });

  it("shows 'IND 2' when 2 indicators are enabled", () => {
    renderToolbar({
      RSI: { enabled: true, period: 14 },
      MACD: { enabled: true, params: { fast: 12, slow: 26, signal: 9 } },
    });
    expect(screen.getByTestId("toolbar-indicators-menu")).toHaveTextContent("IND 2");
  });

  it("renders volume submenu trigger button", () => {
    renderToolbar();
    expect(screen.getByTestId("toolbar-volume-menu")).toBeInTheDocument();
  });

  it("renders MA50 and MA200 toggle buttons", () => {
    renderToolbar();
    expect(screen.getByTestId("toolbar-ma50")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-ma200")).toBeInTheDocument();
  });

  it("renders fullscreen toggle button", () => {
    renderToolbar();
    expect(screen.getByTestId("toolbar-fullscreen")).toBeInTheDocument();
  });

  it("calls onToggleIndicator(RSI) when RSI checkbox is clicked", async () => {
    // WHY userEvent (not fireEvent): Radix UI DropdownMenu uses pointer events
    // internally. fireEvent.click fires only a click event but not the full
    // pointerdown/pointerup sequence that Radix uses to open the dropdown.
    // userEvent.click dispatches the full pointer event sequence, correctly
    // triggering Radix's internal state machine.
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderToolbar();

    await user.click(screen.getByTestId("toolbar-indicators-menu"));

    await waitFor(() => {
      expect(screen.getByTestId("indicator-rsi")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("indicator-rsi"));

    expect(onToggleIndicator).toHaveBeenCalledWith("RSI");
  });

  it("calls onToggleIndicator(MACD) when MACD checkbox is clicked", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderToolbar();
    await user.click(screen.getByTestId("toolbar-indicators-menu"));
    await waitFor(() => expect(screen.getByTestId("indicator-macd")).toBeInTheDocument());
    await user.click(screen.getByTestId("indicator-macd"));
    expect(onToggleIndicator).toHaveBeenCalledWith("MACD");
  });

  it("calls onToggleIndicator(BOLLINGER) when BB checkbox is clicked", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderToolbar();
    await user.click(screen.getByTestId("toolbar-indicators-menu"));
    await waitFor(() => expect(screen.getByTestId("indicator-bollinger")).toBeInTheDocument());
    await user.click(screen.getByTestId("indicator-bollinger"));
    expect(onToggleIndicator).toHaveBeenCalledWith("BOLLINGER");
  });

  it("calls onToggleIndicator(STOCHASTIC) when STOCH is clicked", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderToolbar();
    await user.click(screen.getByTestId("toolbar-indicators-menu"));
    await waitFor(() => expect(screen.getByTestId("indicator-stochastic")).toBeInTheDocument());
    await user.click(screen.getByTestId("indicator-stochastic"));
    expect(onToggleIndicator).toHaveBeenCalledWith("STOCHASTIC");
  });

  it("shows VOL 1 when base volume is active", () => {
    render(
      <ChartToolbar
        showVolume={true}
        onToggleVolume={vi.fn()}
        showMA50={false}
        onToggleMA50={vi.fn()}
        showMA200={false}
        onToggleMA200={vi.fn()}
        isFullscreen={false}
        onFullscreen={vi.fn()}
        indicators={indicators}
        onToggleIndicator={onToggleIndicator}
        showVolMA20={false}
        onToggleVolMA20={vi.fn()}
        showVolProfile={false}
        onToggleVolProfile={vi.fn()}
        showVWAPLine={false}
        onToggleVWAPLine={vi.fn()}
      />,
    );
    // WHY VOL 1: showVolume=true counts as 1 active volume sub-indicator
    expect(screen.getByTestId("toolbar-volume-menu")).toHaveTextContent("VOL 1");
  });

  it("calls onToggleVolMA20 when Vol MA20 is clicked in volume submenu", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    const onToggleVolMA20 = vi.fn();
    render(
      <ChartToolbar
        showVolume={true}
        onToggleVolume={vi.fn()}
        showMA50={false}
        onToggleMA50={vi.fn()}
        showMA200={false}
        onToggleMA200={vi.fn()}
        isFullscreen={false}
        onFullscreen={vi.fn()}
        indicators={indicators}
        onToggleIndicator={onToggleIndicator}
        showVolMA20={false}
        onToggleVolMA20={onToggleVolMA20}
        showVolProfile={false}
        onToggleVolProfile={vi.fn()}
        showVWAPLine={false}
        onToggleVWAPLine={vi.fn()}
      />,
    );

    await user.click(screen.getByTestId("toolbar-volume-menu"));
    await waitFor(() => expect(screen.getByTestId("vol-ma20")).toBeInTheDocument());
    await user.click(screen.getByTestId("vol-ma20"));
    expect(onToggleVolMA20).toHaveBeenCalled();
  });
});

// ── DrawingPalette unit tests ─────────────────────────────────────────────────

import { DrawingPalette } from "@/components/instrument/DrawingPalette";

describe("DrawingPalette — Wave C", () => {
  it("renders all 8 palette buttons (CURSOR + 7 drawing tools)", () => {
    const onSelectTool = vi.fn();
    render(<DrawingPalette activeTool={null} onSelectTool={onSelectTool} annotationCount={0} />);

    // WHY check data-testid pattern: each button has a unique testid derived from
    // the tool name (e.g., "drawing-tool-trend-line").
    expect(screen.getByTestId("drawing-tool-cursor")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-trend-line")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-horizontal-level")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-rectangle")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-arrow")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-fib-retracement")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-parallel-channel")).toBeInTheDocument();
    expect(screen.getByTestId("drawing-tool-text")).toBeInTheDocument();
  });

  it("CURSOR button is active when activeTool is null", () => {
    render(<DrawingPalette activeTool={null} onSelectTool={vi.fn()} annotationCount={0} />);
    // WHY aria-pressed: the button uses aria-pressed="true" for the active state.
    // This is the standard accessibility pattern for toggle buttons.
    expect(screen.getByTestId("drawing-tool-cursor")).toHaveAttribute("aria-pressed", "true");
  });

  it("TREND_LINE button is active when activeTool is TREND_LINE", () => {
    render(<DrawingPalette activeTool="TREND_LINE" onSelectTool={vi.fn()} annotationCount={0} />);
    expect(screen.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("drawing-tool-cursor")).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onSelectTool(TREND_LINE) when trend line button clicked", () => {
    const onSelectTool = vi.fn();
    render(<DrawingPalette activeTool={null} onSelectTool={onSelectTool} annotationCount={0} />);
    fireEvent.click(screen.getByTestId("drawing-tool-trend-line"));
    expect(onSelectTool).toHaveBeenCalledWith("TREND_LINE");
  });

  it("calls onSelectTool(null) when CURSOR button clicked", () => {
    const onSelectTool = vi.fn();
    render(<DrawingPalette activeTool="TREND_LINE" onSelectTool={onSelectTool} annotationCount={0} />);
    fireEvent.click(screen.getByTestId("drawing-tool-cursor"));
    expect(onSelectTool).toHaveBeenCalledWith(null);
  });

  it("calls onSelectTool(null) when the same active tool is clicked again (toggle off)", () => {
    const onSelectTool = vi.fn();
    // WHY toggle-off: clicking an already-armed tool should disarm it (same UX as TradingView)
    render(<DrawingPalette activeTool="HORIZONTAL_LEVEL" onSelectTool={onSelectTool} annotationCount={0} />);
    fireEvent.click(screen.getByTestId("drawing-tool-horizontal-level"));
    expect(onSelectTool).toHaveBeenCalledWith(null);
  });

  it("calls onSelectTool(RECTANGLE) when rectangle button clicked", () => {
    const onSelectTool = vi.fn();
    render(<DrawingPalette activeTool={null} onSelectTool={onSelectTool} annotationCount={0} />);
    fireEvent.click(screen.getByTestId("drawing-tool-rectangle"));
    expect(onSelectTool).toHaveBeenCalledWith("RECTANGLE");
  });
});

// ── Indicator computation unit tests ──────────────────────────────────────────

import {
  computeRSI,
  computeMACD,
  computeBollinger,
  computeATR,
  computeStochastic,
  computeOBV,
  computeVWAP,
  computeVolumeMA,
  computeVolumeProfile,
  type FormattedBar,
} from "@/lib/instrument-context";

/**
 * generateFormattedBars — factory for FormattedBar[] with deterministic prices.
 *
 * WHY rising then falling pattern: tests need bars that go up and down to
 * exercise both the gain and loss paths in RSI, MACD crossovers in Stochastic,
 * and volume accumulation in OBV.
 */
function generateFormattedBars(count: number, startPrice = 100): FormattedBar[] {
  const bars: FormattedBar[] = [];
  let price = startPrice;
  const startTime = Math.floor(new Date("2026-01-01").getTime() / 1000);
  const DAY = 86400;
  for (let i = 0; i < count; i++) {
    // Sine-wave price movement: creates predictable up/down cycles
    const change = Math.sin(i * 0.3) * 2;
    price = Math.max(90, price + change);
    bars.push({
      time: startTime + i * DAY,
      open: price - 0.3,
      high: price + 0.8,
      low: price - 0.8,
      close: price,
      volume: 1_000_000 + Math.abs(change) * 200_000,
    });
  }
  return bars;
}

describe("computeRSI — indicator math", () => {
  it("returns empty array when bars < period + 1", () => {
    const bars = generateFormattedBars(10);
    expect(computeRSI(bars, 14)).toEqual([]);
  });

  it("returns correct length for 30 bars, period 14", () => {
    // WHY 30 bars with period 14: first valid RSI at index 14 (15th bar), then
    // one RSI value per subsequent bar. Length = 30 - 14 = 16.
    const bars = generateFormattedBars(30);
    const result = computeRSI(bars, 14);
    expect(result.length).toBe(30 - 14);
  });

  it("RSI values are bounded [0, 100]", () => {
    const bars = generateFormattedBars(50);
    const result = computeRSI(bars, 14);
    result.forEach(({ value }) => {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    });
  });

  it("RSI values have correct time stamps (start at bar[period])", () => {
    const bars = generateFormattedBars(20);
    const result = computeRSI(bars, 14);
    // First RSI point should have the time of bars[14] (0-indexed)
    expect(result[0].time).toBe(bars[14].time);
  });

  it("RSI is 100 when all bars are up (all gains, no losses)", () => {
    // Strictly increasing prices → avgLoss = 0 → RSI = 100
    const bars: FormattedBar[] = Array.from({ length: 20 }, (_, i) => ({
      time: i * 86400,
      open: 100 + i - 0.1,
      high: 100 + i + 0.5,
      low: 100 + i - 0.5,
      close: 100 + i, // always increasing
      volume: 1_000_000,
    }));
    const result = computeRSI(bars, 14);
    // All changes are positive → RSI = 100
    expect(result[0].value).toBe(100);
  });
});

describe("computeMACD — indicator math", () => {
  it("returns empty array with fewer than slow+signal bars", () => {
    // WHY slow=26, signal=9: need at least 26+9=35 bars to get any MACD output.
    const bars = generateFormattedBars(30);
    expect(computeMACD(bars, 12, 26, 9)).toEqual([]);
  });

  it("returns correct shape for 50 bars", () => {
    const bars = generateFormattedBars(50);
    const result = computeMACD(bars, 12, 26, 9);
    // Each MACD point has macd, signal, histogram
    expect(result.length).toBeGreaterThan(0);
    result.forEach((point) => {
      expect(typeof point.macd).toBe("number");
      expect(typeof point.signal).toBe("number");
      expect(typeof point.histogram).toBe("number");
      // histogram = macd - signal (algebraic identity)
      expect(Math.abs(point.histogram - (point.macd - point.signal))).toBeLessThan(1e-10);
    });
  });
});

describe("computeBollinger — indicator math", () => {
  it("returns empty array when bars < period", () => {
    const bars = generateFormattedBars(15);
    expect(computeBollinger(bars, 20)).toEqual([]);
  });

  it("upper band > middle > lower band for every point", () => {
    const bars = generateFormattedBars(50);
    const result = computeBollinger(bars, 20, 2);
    result.forEach(({ upper, middle, lower }) => {
      expect(upper).toBeGreaterThan(middle);
      expect(middle).toBeGreaterThan(lower);
    });
  });

  it("middle band equals SMA-20 of closes", () => {
    const bars = generateFormattedBars(25);
    const result = computeBollinger(bars, 20, 2);
    // First BB point is at index 19 (bars[19] through bars[0] form the first window)
    const sma20 = bars.slice(0, 20).reduce((s, b) => s + b.close, 0) / 20;
    expect(result[0].middle).toBeCloseTo(sma20, 8);
  });
});

describe("computeATR — indicator math", () => {
  it("returns empty array when bars < period + 1", () => {
    const bars = generateFormattedBars(10);
    expect(computeATR(bars, 14)).toEqual([]);
  });

  it("ATR values are always positive", () => {
    const bars = generateFormattedBars(30);
    computeATR(bars, 14).forEach(({ value }) => {
      expect(value).toBeGreaterThan(0);
    });
  });

  it("returns correct count for 30 bars, period 14", () => {
    const bars = generateFormattedBars(30);
    // First ATR at bars[14], then one per bar. Length = 30 - 14 = 16.
    expect(computeATR(bars, 14).length).toBe(30 - 14);
  });
});

describe("computeStochastic — indicator math", () => {
  it("returns empty for insufficient bars", () => {
    const bars = generateFormattedBars(10);
    expect(computeStochastic(bars, 14, 3, 3)).toEqual([]);
  });

  it("%K and %D are bounded [0, 100]", () => {
    const bars = generateFormattedBars(50);
    computeStochastic(bars, 14, 3, 3).forEach(({ k, d }) => {
      expect(k).toBeGreaterThanOrEqual(0);
      expect(k).toBeLessThanOrEqual(100);
      expect(d).toBeGreaterThanOrEqual(0);
      expect(d).toBeLessThanOrEqual(100);
    });
  });
});

describe("computeOBV — indicator math", () => {
  it("returns empty array for fewer than 2 bars", () => {
    // WHY: computeOBV requires at least 2 bars to compute a meaningful change.
    // A single bar has no "previous close" to compare against.
    expect(computeOBV([])).toEqual([]);
    // WHY also empty for 1 bar: the implementation requires bars.length >= 2
    // before computing the first OBV value (needs prev close for the direction check).
    expect(computeOBV(generateFormattedBars(1))).toHaveLength(0);
  });

  it("OBV increases on up-day and decreases on down-day", () => {
    // Two bars: bar[0] close=100, bar[1] close=101 (up day)
    const upDay: FormattedBar[] = [
      { time: 0, open: 99, high: 102, low: 98, close: 100, volume: 1_000_000 },
      { time: 1, open: 100, high: 103, low: 99, close: 101, volume: 2_000_000 },
    ];
    const result = computeOBV(upDay);
    expect(result[0].value).toBe(0);
    expect(result[1].value).toBe(2_000_000); // +volume on up day

    // Down day: bar[1] close < bar[0] close
    const downDay: FormattedBar[] = [
      { time: 0, open: 101, high: 103, low: 99, close: 101, volume: 1_000_000 },
      { time: 1, open: 101, high: 102, low: 98, close: 99, volume: 1_500_000 },
    ];
    const result2 = computeOBV(downDay);
    expect(result2[1].value).toBe(-1_500_000); // -volume on down day
  });
});

describe("computeVWAP — indicator math", () => {
  it("returns one value per bar", () => {
    const bars = generateFormattedBars(20);
    expect(computeVWAP(bars)).toHaveLength(20);
  });

  it("VWAP is between high and low for each bar", () => {
    // For a flat-price scenario (all bars identical), VWAP = typical price = close
    const flatBars: FormattedBar[] = Array.from({ length: 10 }, (_, i) => ({
      time: i,
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 1_000_000,
    }));
    const result = computeVWAP(flatBars);
    // Typical price = (101 + 99 + 100) / 3 = 100
    result.forEach(({ value }) => {
      expect(value).toBeCloseTo(100, 5);
    });
  });
});

describe("computeVolumeMA — indicator math", () => {
  it("returns empty when bars < period", () => {
    const bars = generateFormattedBars(15);
    expect(computeVolumeMA(bars, 20)).toEqual([]);
  });

  it("returns n - period + 1 values for n bars", () => {
    const bars = generateFormattedBars(30);
    expect(computeVolumeMA(bars, 20)).toHaveLength(30 - 20 + 1);
  });
});

describe("computeVolumeProfile — indicator math", () => {
  it("returns empty array for empty bars", () => {
    expect(computeVolumeProfile([])).toEqual([]);
  });

  it("returns numBuckets buckets for non-empty bars", () => {
    const bars = generateFormattedBars(30);
    expect(computeVolumeProfile(bars, 24)).toHaveLength(24);
  });

  it("exactly one bucket is marked as POC", () => {
    const bars = generateFormattedBars(30);
    const profile = computeVolumeProfile(bars, 24);
    const pocCount = profile.filter((b) => b.isPOC).length;
    expect(pocCount).toBe(1);
  });

  it("total volume in profile equals sum of bar volumes", () => {
    const bars = generateFormattedBars(30);
    const profile = computeVolumeProfile(bars, 24);
    const totalProfile = profile.reduce((s, b) => s + b.volume, 0);
    const totalBars = bars.reduce((s, b) => s + b.volume, 0);
    expect(totalProfile).toBeCloseTo(totalBars, 0);
  });
});

// ── localStorage persistence tests ────────────────────────────────────────────
// WHY no re-import of createDefaultIndicatorState: it was already imported above
// for the ChartToolbar tests. TypeScript disallows duplicate identifier imports
// from the same module. The imports at the top of the "ChartToolbar — Wave C"
// describe block are module-scoped and available here.

import {
  loadIndicatorsFromStorage,
  saveIndicatorsToStorage,
} from "@/lib/instrument-context";

describe("indicator localStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("loadIndicatorsFromStorage returns defaults when localStorage is empty", () => {
    const loaded = loadIndicatorsFromStorage();
    const defaults = createDefaultIndicatorState();
    // WHY deep equality: every indicator should match the default config exactly
    expect(loaded).toEqual(defaults);
  });

  it("saveIndicatorsToStorage + loadIndicatorsFromStorage round-trip", () => {
    const state = createDefaultIndicatorState();
    state.RSI = { enabled: true, period: 14 };
    state.MACD = { enabled: true, params: { fast: 12, slow: 26, signal: 9 } };
    saveIndicatorsToStorage(state);

    const loaded = loadIndicatorsFromStorage();
    expect(loaded.RSI.enabled).toBe(true);
    expect(loaded.MACD.enabled).toBe(true);
    // Non-modified indicators should remain as defaults (disabled)
    expect(loaded.ATR.enabled).toBe(false);
  });

  it("merges stored config with defaults (new indicators added since save)", () => {
    // WHY test merging: if a user has an old saved config (before a new indicator
    // was added), loadIndicatorsFromStorage should merge defaults for the new key.
    // Simulate this by storing a config without the VWAP key.
    const partialConfig = { RSI: { enabled: true, period: 14 } };
    localStorage.setItem("worldview:chart:indicators:v1", JSON.stringify(partialConfig));

    const loaded = loadIndicatorsFromStorage();
    // RSI should reflect the stored config
    expect(loaded.RSI.enabled).toBe(true);
    // VWAP (not in stored config) should default to enabled:false
    expect(loaded.VWAP).toEqual({ enabled: false });
  });

  it("returns defaults when stored JSON is invalid", () => {
    localStorage.setItem("worldview:chart:indicators:v1", "NOT_JSON{{{");
    const loaded = loadIndicatorsFromStorage();
    expect(loaded).toEqual(createDefaultIndicatorState());
  });
});

// ── OHLCVChart integration tests ──────────────────────────────────────────────

import { OHLCVChart } from "@/components/instrument/OHLCVChart";

describe("OHLCVChart — Wave C integration", () => {
  const wrapper = makeWrapper();

  afterEach(() => {
    cleanup();
  });

  it("renders the drawing palette on the left side", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });
    // WHY data-testid: DrawingPalette has data-testid="drawing-palette"
    expect(screen.getByTestId("drawing-palette")).toBeInTheDocument();
  });

  it("renders the chart toolbar with indicators dropdown", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });
    expect(screen.getByTestId("chart-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar-indicators-menu")).toBeInTheDocument();
  });

  it("renders the volume submenu button", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });
    expect(screen.getByTestId("toolbar-volume-menu")).toBeInTheDocument();
  });

  it("renders timeframe selector buttons", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });
    expect(screen.getByText("5M")).toBeInTheDocument();
    expect(screen.getByText("1H")).toBeInTheDocument();
    expect(screen.getByText("1D")).toBeInTheDocument();
    expect(screen.getByText("1W")).toBeInTheDocument();
    expect(screen.getByText("1M")).toBeInTheDocument();
  });

  it("the drawing canvas overlay is present in the DOM", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });
    // WHY: DrawingCanvas always renders (even with null converters) — it's an SVG
    // that becomes interactive when converters are set post-chart-init.
    expect(screen.getByTestId("drawing-canvas")).toBeInTheDocument();
  });

  it("clicking a drawing tool arms it in the palette", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("drawing-tool-trend-line"));
    });

    // WHY aria-pressed: the button reflects active tool state via aria-pressed.
    expect(screen.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "true");
  });

  it("clicking cursor deselects active tool", async () => {
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });

    // Arm a tool first
    await act(async () => {
      fireEvent.click(screen.getByTestId("drawing-tool-trend-line"));
    });
    expect(screen.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "true");

    // Click cursor to deselect
    await act(async () => {
      fireEvent.click(screen.getByTestId("drawing-tool-cursor"));
    });
    expect(screen.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("drawing-tool-cursor")).toHaveAttribute("aria-pressed", "true");
  });

  it("shows Chart unavailable fallback when lightweight-charts fails to load", async () => {
    vi.doMock("lightweight-charts", () => {
      throw new Error("Module load failed");
    });

    const { OHLCVChart: OHLCVChartWithError } = await import(
      "@/components/instrument/OHLCVChart"
    );

    render(<OHLCVChartWithError instrumentId="ins-001" />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Chart unavailable")).toBeInTheDocument();
    });

    // Restore mock for subsequent tests
    vi.doMock("lightweight-charts", () => ({
      createChart: vi.fn(() => ({
        addCandlestickSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
        addHistogramSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
        addLineSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
        priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
        applyOptions: vi.fn(),
        timeScale: vi.fn(() => ({
          fitContent: vi.fn(),
          timeToCoordinate: vi.fn(() => null),
          coordinateToTime: vi.fn(() => null),
        })),
        remove: vi.fn(),
      })),
    }));
  });
});
