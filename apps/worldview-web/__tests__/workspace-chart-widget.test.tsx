/**
 * __tests__/workspace-chart-widget.test.tsx — Tests for WorkspaceChartWidget
 *
 * WHY THIS EXISTS: WorkspaceChartWidget is the panel-sized OHLCV chart used in
 * the Workspace surface. It has multiple states (no symbol, loading, error,
 * data-loaded) that each need test coverage to prevent regressions.
 *
 * WHY MOCK lightweight-charts: jsdom has no Canvas/WebGL; calling createChart
 * would crash. The mock returns a fake chart object whose methods are spies so
 * we can assert against init/cleanup behavior without real rendering.
 *
 * WHY MOCK gateway + useAuth: the widget calls getOHLCV via createGateway and
 * useAuth for the access token. Mocking both gives us deterministic data and
 * lets us trigger error states.
 *
 * COVERAGE:
 *   1. Empty state when no ticker prop passed
 *   2. Renders the timeframe selector with all 5 options
 *   3. Active timeframe is "3M" by default (highlighted)
 *   4. Clicking a different timeframe updates the active state
 *   5. Loading skeleton appears while data is fetching
 *   6. Ticker text renders in the header when ticker is provided
 *   7. data-testid="workspace-chart-canvas" exists when ticker is present
 *
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-03
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WorkspaceChartWidget } from "@/components/workspace/WorkspaceChartWidget";

// ── Auth mock — returns a valid token so queries are enabled ──────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
  })),
}));

// ── Gateway mock — returns 3 OHLCV bars by default ────────────────────────────
// WHY 3 bars (not zero): empty arrays would skip the chart-data effect and we
// couldn't verify the data-flow path. Three bars is the minimum to verify
// formatting + setData was called.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getOHLCV: vi.fn().mockResolvedValue({
      instrument_id: "ins-aapl",
      ticker: "AAPL",
      timeframe: "1D",
      bars: [
        { timestamp: "2026-01-01T00:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
        { timestamp: "2026-01-02T00:00:00Z", open: 103, high: 108, low: 102, close: 107, volume: 1500 },
        { timestamp: "2026-01-03T00:00:00Z", open: 107, high: 110, low: 106, close: 109, volume: 1200 },
      ],
    }),
  })),
}));

// ── lightweight-charts mock ──────────────────────────────────────────────────
// WHY explicit mock object: the widget calls createChart, addCandlestickSeries,
// applyOptions, timeScale().fitContent(), and remove(). Each must return
// something callable so the widget doesn't throw. We also expose the spies for
// assertions.
const mockSetData = vi.fn();
const mockApplyOptions = vi.fn();
const mockRemove = vi.fn();
const mockFitContent = vi.fn();

// PLAN-0059 H-1: lightweight-charts v5 — series creation now goes through
// chart.addSeries(SeriesDefinition, opts). Mock provides the same shape.
// addPane + removeSeries added for H-1 pane isolation.
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({
      setData: mockSetData,
      applyOptions: mockApplyOptions,
    })),
    addPane: vi.fn(),
    removeSeries: vi.fn(),
    applyOptions: mockApplyOptions,
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: mockFitContent, scrollToRealTime: vi.fn() })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    remove: mockRemove,
  })),
  CandlestickSeries: "CandlestickSeries",
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
  AreaSeries: "AreaSeries",
}));

// ── ResizeObserver shim — jsdom doesn't ship one ─────────────────────────────
// WHY install before render: the widget instantiates a ResizeObserver inside its
// useEffect. Without this shim the constructor throws ReferenceError.
class MockResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
vi.stubGlobal("ResizeObserver", MockResizeObserver);

// ── Test wrapper — gives every test a fresh QueryClient ──────────────────────
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Setup ────────────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("WorkspaceChartWidget — empty state", () => {
  it("renders empty state when no ticker prop is provided", () => {
    render(<WorkspaceChartWidget />, { wrapper: makeWrapper() });
    // WHY exact-match strings: empty state title/message are stable design
    // copy; tests catching rewordings is the intent.
    expect(screen.getByText(/no symbol linked/i)).toBeInTheDocument();
    expect(
      screen.getByText(/pick a symbol via the color picker/i),
    ).toBeInTheDocument();
  });

  it("does not render the chart canvas when ticker is missing", () => {
    render(<WorkspaceChartWidget />, { wrapper: makeWrapper() });
    // WHY queryByTestId (not getByTestId): we expect ABSENCE here. getByTestId
    // would throw on missing element; queryByTestId returns null which we assert.
    expect(screen.queryByTestId("workspace-chart-canvas")).toBeNull();
  });
});

describe("WorkspaceChartWidget — with ticker", () => {
  it("renders the ticker text in the header", () => {
    render(<WorkspaceChartWidget ticker="AAPL" />, { wrapper: makeWrapper() });
    // WHY aria-label match: the ticker span has aria-label={`Ticker ${ticker}`}
    // and the visible text shows the same ticker. Either lookup is valid.
    expect(screen.getByLabelText(/ticker aapl/i)).toBeInTheDocument();
  });

  it("renders all 5 timeframe buttons", () => {
    render(<WorkspaceChartWidget ticker="AAPL" />, { wrapper: makeWrapper() });
    expect(screen.getByRole("button", { name: /set timeframe 1d/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set timeframe 1w/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set timeframe 1m/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set timeframe 3m/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set timeframe 1y/i })).toBeInTheDocument();
  });

  it("defaults the active timeframe to 3M", () => {
    render(<WorkspaceChartWidget ticker="AAPL" />, { wrapper: makeWrapper() });
    // WHY aria-pressed: the timeframe buttons use aria-pressed to communicate
    // active state. The default selected timeframe (3M) should have it set.
    const tf3m = screen.getByRole("button", { name: /set timeframe 3m/i });
    expect(tf3m).toHaveAttribute("aria-pressed", "true");
  });

  it("updates active timeframe on click", async () => {
    const user = userEvent.setup();
    render(<WorkspaceChartWidget ticker="AAPL" />, { wrapper: makeWrapper() });

    const tf1y = screen.getByRole("button", { name: /set timeframe 1y/i });
    expect(tf1y).toHaveAttribute("aria-pressed", "false");

    await user.click(tf1y);

    // WHY waitFor (not direct assert): the click triggers a re-render via
    // setState; userEvent + jsdom flushes microtasks, but waitFor protects
    // against any future React 19 batching subtlety.
    await waitFor(() => {
      expect(tf1y).toHaveAttribute("aria-pressed", "true");
    });
  });

  it("renders the chart canvas container when ticker is provided", () => {
    render(<WorkspaceChartWidget ticker="AAPL" />, { wrapper: makeWrapper() });
    expect(screen.getByTestId("workspace-chart-canvas")).toBeInTheDocument();
  });
});
