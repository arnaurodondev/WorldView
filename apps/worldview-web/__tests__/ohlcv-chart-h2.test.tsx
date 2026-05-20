/**
 * __tests__/ohlcv-chart-h2.test.tsx — PLAN-0059 H-1/H-2 feature tests
 *
 * WHY THIS EXISTS: Covers the H-1/H-2 wave additions to OHLCVChart:
 *   1. CrosshairHUD — verifies it mounts when the chart initialises.
 *   2. Log scale toggle — verifies priceScale("right").applyOptions is called
 *      with mode:1 when the LOG button is clicked.
 *   3. Compare overlay — verifies a second series is added when a compare ticker
 *      is submitted via the +CMP popover input.
 *
 * WHY mock lightweight-charts for all tests:
 *   lightweight-charts uses browser Canvas/WebGL APIs unavailable in jsdom.
 *   The chart rendering is not the subject of these tests — we verify state
 *   management, gateway calls, and series creation counts.
 *
 * WHY vi.mock at module level (not inside tests):
 *   Vitest hoists vi.mock() to the top of the module. Inline mocks defined
 *   inside individual tests run AFTER the module is already resolved with the
 *   top-level mock, so they won't replace the module for that test's imports.
 *   All mock behaviour is defined once at the top and overridden via mockReturnValue
 *   or mockResolvedValue inside individual tests.
 *
 * WHO USES IT: CI pre-merge gate for PLAN-0059 H-1/H-2.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { act } from "react";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Shared mock: createSeriesMarkers ──────────────────────────────────────────

// WHY a module-level mock return for createSeriesMarkers: the test for news markers
// needs to assert that setMarkers was called with the right articles. We capture
// the mock instance in a variable here so tests can inspect calls.
const mockSetMarkers = vi.fn();
const mockMarkersPlugin = { setMarkers: mockSetMarkers };

// ── Mock: lightweight-charts ──────────────────────────────────────────────────

// WHY mock lightweight-charts: WebGL APIs not available in jsdom.
// The v5 mock includes:
//   - createChart() → returns a mock chart with addSeries, priceScale, etc.
//   - addSeries() → returns a mock series with setData/applyOptions
//   - createSeriesMarkers() → returns our mockMarkersPlugin (captured above)
//   - addPane() → returns undefined (we only care that it was called)
//
// WHY track addSeries calls: test 3 verifies a second series is added for the
// compare overlay. We capture the mock function reference so tests can inspect
// the call count.
const mockAddSeries = vi.fn(() => ({
  setData: vi.fn(),
  applyOptions: vi.fn(),
}));

const mockPriceScaleApplyOptions = vi.fn();

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: mockAddSeries,
    addPane: vi.fn(),
    priceScale: vi.fn(() => ({
      applyOptions: mockPriceScaleApplyOptions,
    })),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
      scrollToRealTime: vi.fn(),
      timeToCoordinate: vi.fn(() => null),
      coordinateToTime: vi.fn(() => null),
      setVisibleLogicalRange: vi.fn(),
    })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
    removeSeries: vi.fn(),
  })),
  // WHY string literal exports: OHLCVChart imports these as SeriesDefinition
  // values and passes them to chart.addSeries() as the first argument.
  CandlestickSeries: "CandlestickSeries",
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
  AreaSeries: "AreaSeries",
  // WHY createSeriesMarkers: OHLCVChart v5 uses this plugin API for news markers.
  // The mock returns our pre-built plugin object so we can assert setMarkers calls.
  createSeriesMarkers: vi.fn(() => mockMarkersPlugin),
}));

// ── Mock: next/navigation ─────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// ── Mock: gateway ─────────────────────────────────────────────────────────────

// WHY capture mockGateway: test 3 needs to assert that getOHLCV is called a
// second time (for the compare instrument). We keep a reference to the gateway
// mock object so tests can override specific methods and inspect call counts.
const mockGetOHLCV = vi.fn().mockResolvedValue({
  instrument_id: "ins-001",
  ticker: "AAPL",
  timeframe: "1D",
  bars: generateTestBars(60),
});

const mockSearchInstruments = vi.fn().mockResolvedValue({
  results: [{ instrument_id: "ins-002", entity_id: "ent-002", ticker: "MSFT", name: "Microsoft", exchange: "NASDAQ", type: "equity" }],
  query: "MSFT",
});

const mockGetEntityNews = vi.fn().mockResolvedValue({
  articles: [],
  total: 0,
});

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getOHLCV: mockGetOHLCV,
    searchInstruments: mockSearchInstruments,
    getEntityNews: mockGetEntityNews,
    refreshToken: vi.fn().mockResolvedValue({ access_token: "tok", user: {}, expires_in: 900 }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

// ── Mock: useAuth ─────────────────────────────────────────────────────────────

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    logout: vi.fn(),
  })),
}));

// ── Mock: instrument-context (IDB ops only) ────────────────────────────────────

vi.mock("@/lib/instrument-context", async () => {
  const actual = await vi.importActual<typeof import("@/lib/instrument-context")>(
    "@/lib/instrument-context",
  );
  return {
    ...actual,
    // WHY mock only IDB ops: computation functions (RSI, MACD etc.) are tested
    // in chart-toolbar-wave-c.test.tsx; here we only care about H-2 features.
    loadAnnotationsFromIDB: vi.fn().mockResolvedValue([]),
    saveAnnotationsToIDB: vi.fn().mockResolvedValue(undefined),
  };
});

// ── Test helpers ──────────────────────────────────────────────────────────────

/**
 * generateTestBars — creates N synthetic OHLCV bars.
 * WHY forward declaration: vi.mock() hoisting runs the factory before `function`
 * declarations in the module body. Putting the helper here (above the imports
 * that use it) ensures it's defined before the mock factory executes.
 */
function generateTestBars(count: number) {
  const bars = [];
  let price = 100;
  const startTime = Math.floor(new Date("2026-01-01").getTime() / 1000);
  const DAY = 86400;
  for (let i = 0; i < count; i++) {
    const change = ((i % 7) - 3) * 0.5;
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

// ── Import under test ─────────────────────────────────────────────────────────

import { OHLCVChart } from "@/components/instrument/chart/OHLCVChart";

// ── Tests ─────────────────────────────────────────────────────────────────────

// PLAN-0090 T-B-01 removed CrosshairHUD from OHLCVChart. The tests below
// pin output from the deleted feature; T-E-02 may replace with assertions
// against the new minimalist chart surface.
describe.skip("PLAN-0059 H-2 — CrosshairHUD rendering (obsolete; see PLAN-0090 T-B-01)", () => {
  afterEach(() => {
    cleanup();
  });

  it("test 1: CrosshairHUD is rendered when chart initialises", async () => {
    // WHY we test for the CrosshairHUD wrapper div instead of its content:
    // CrosshairHUD renders null when data is null (no crosshair hover yet).
    // To detect it in the DOM we look for the component mount — which happens
    // because OHLCVChart unconditionally renders <CrosshairHUD .../>.
    // CrosshairHUD uses `if (!data) return null;` so the element is absent
    // until a crosshair move event fires.
    //
    // Instead we verify: the chart.subscribeCrosshairMove was called, which
    // means CrosshairHUD mounted and registered its handler. This is the
    // strongest assertion possible without mocking the crosshair event.
    const wrapper = makeWrapper();
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });

    // chart.subscribeCrosshairMove is called inside CrosshairHUD's useEffect.
    // WHY dynamic import: the chart instance lives inside the mock — we verify
    // it was called via the mock's recorded calls.
    const { createChart } = await import("lightweight-charts");
    const chartMock = (createChart as ReturnType<typeof vi.fn>).mock.results[0]?.value;
    expect(chartMock).toBeDefined();

    // If the chart was created and CrosshairHUD mounted and wired its handler,
    // subscribeCrosshairMove should have been called.
    // WHY eventually (waitFor): chart init is async (dynamic import inside useEffect).
    await waitFor(() => {
      expect(chartMock.subscribeCrosshairMove).toHaveBeenCalled();
    });
  });
});

describe("PLAN-0059 H-2 — Log scale toggle", () => {
  beforeEach(() => {
    // WHY clearAllMocks: priceScale.applyOptions accumulates calls across tests.
    // Clearing before each test isolates the assertion to this test's click.
    mockPriceScaleApplyOptions.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  it("test 2: clicking LOG button calls priceScale applyOptions with mode 1", async () => {
    const wrapper = makeWrapper();
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });

    // Find the LOG button. It is rendered inline in OHLCVChart (not via ChartToolbar).
    // WHY aria-label: the button has aria-label="Toggle logarithmic price scale".
    const logButton = screen.getByRole("button", { name: /toggle logarithmic price scale/i });
    expect(logButton).toBeInTheDocument();

    // Click LOG to toggle on
    await act(async () => {
      fireEvent.click(logButton);
    });

    // After the click, the logScale state flips to true and the useEffect
    // calls chart.priceScale("right").applyOptions({ mode: 1 }).
    // WHY mode 1: lightweight-charts PriceScaleMode.Logarithmic = 1.
    await waitFor(() => {
      const calls = mockPriceScaleApplyOptions.mock.calls;
      // Find the call that sets mode:1 (log scale on)
      const logOnCall = calls.find((args) => args[0]?.mode === 1);
      expect(logOnCall).toBeDefined();
    });
  });
});

// PLAN-0090 T-B-01 removed the compare-overlay UI from OHLCVChart.
describe.skip("PLAN-0059 H-2 — Compare overlay (obsolete; see PLAN-0090 T-B-01)", () => {
  beforeEach(() => {
    mockAddSeries.mockClear();
    mockGetOHLCV.mockClear();
    mockSearchInstruments.mockClear();

    // Reset OHLCV mock to return primary bars for ins-001
    mockGetOHLCV.mockResolvedValue({
      instrument_id: "ins-001",
      ticker: "AAPL",
      timeframe: "1D",
      bars: generateTestBars(60),
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("test 3: compare overlay adds a second series on ticker submit", async () => {
    // WHY mock OHLCV to return compare data for ins-002: the compare flow calls
    // gateway.getOHLCV(ins-002, ...) AFTER the initial ins-001 load completes.
    // We track call count to distinguish the two calls.
    let ohlcvCallCount = 0;
    mockGetOHLCV.mockImplementation((instrumentId: string) => {
      ohlcvCallCount++;
      if (instrumentId === "ins-001") {
        return Promise.resolve({
          instrument_id: "ins-001",
          ticker: "AAPL",
          timeframe: "1D",
          bars: generateTestBars(60),
        });
      }
      // Second call: compare instrument (ins-002 / MSFT)
      return Promise.resolve({
        instrument_id: "ins-002",
        ticker: "MSFT",
        timeframe: "1D",
        bars: generateTestBars(60),
      });
    });

    const wrapper = makeWrapper();
    await act(async () => {
      render(<OHLCVChart instrumentId="ins-001" />, { wrapper });
    });

    // Wait for the initial OHLCV load
    await waitFor(() => {
      expect(ohlcvCallCount).toBeGreaterThanOrEqual(1);
    });

    // Record addSeries call count before compare (primary series already added)
    const addSeriesCountBefore = mockAddSeries.mock.calls.length;

    // Click the +CMP button to open the compare popover
    const cmpButton = screen.getByTestId("toolbar-compare");
    await act(async () => {
      fireEvent.click(cmpButton);
    });

    // Type "MSFT" in the input and press Enter
    const input = await screen.findByRole("textbox", { name: /enter ticker to compare/i });
    await act(async () => {
      fireEvent.change(input, { target: { value: "MSFT" } });
      fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    });

    // Wait for the compare flow to complete: searchInstruments → getOHLCV → addSeries
    await waitFor(() => {
      // searchInstruments should have been called with "MSFT"
      expect(mockSearchInstruments).toHaveBeenCalledWith("MSFT", 1);
    });

    await waitFor(() => {
      // getOHLCV should have been called a second time (for ins-002)
      expect(ohlcvCallCount).toBeGreaterThanOrEqual(2);
    });

    await waitFor(() => {
      // addSeries should have been called at least once MORE than before the compare
      // (the compare LineSeries is added after the initial series batch).
      const addSeriesCountAfter = mockAddSeries.mock.calls.length;
      expect(addSeriesCountAfter).toBeGreaterThan(addSeriesCountBefore);
    });
  });
});
