/**
 * components/instrument/chart/__tests__/OHLCVChart.periods.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation): pins the chart's period-selector
 * contract end-to-end through the data layer:
 *   1. All 6 period pills render with 1D selected by default.
 *   2. The fetch sends the preset's derived bar resolution + explicit start
 *      to the price-history endpoint.
 *   3. The fetched bars land in the SHARED qk.instruments.ohlcv cache slot —
 *      regression guard for the Round-1 key-mismatch fix (the old bare
 *      ["ohlcv", ...] key silently disconnected QuoteTab's SessionStatsStrip).
 *   4. Crosshair hover shows the OHLC+V legend for the hovered candle.
 *
 * WHY mock lightweight-charts: WebGL/Canvas unavailable in jsdom — chart
 * rendering is not under test; state, gateway params, and cache shape are.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { act } from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mock: lightweight-charts ──────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock factories are hoisted above imports — handles must
// be created in a hoisted scope to be referenced both by the factory and tests.
const h = vi.hoisted(() => {
  const subscribeCrosshairMove = vi.fn();
  const setVisibleRange = vi.fn();
  const scrollToRealTime = vi.fn();
  const timeScale = vi.fn(() => ({
    fitContent: vi.fn(),
    scrollToRealTime,
    setVisibleRange,
    timeToCoordinate: vi.fn(() => null),
    coordinateToTime: vi.fn(() => null),
    setVisibleLogicalRange: vi.fn(),
  }));
  const addSeries = vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() }));
  const createChart = vi.fn(() => ({
    addSeries,
    addPane: vi.fn(() => ({ setOptions: vi.fn() })),
    panes: vi.fn(() => []),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    applyOptions: vi.fn(),
    timeScale,
    subscribeCrosshairMove,
    unsubscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
    removeSeries: vi.fn(),
  }));
  return { createChart, addSeries, subscribeCrosshairMove, setVisibleRange, scrollToRealTime };
});

vi.mock("lightweight-charts", () => ({
  createChart: h.createChart,
  CandlestickSeries: "CandlestickSeries",
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
  AreaSeries: "AreaSeries",
  createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
}));

// ── Mock: gateway ─────────────────────────────────────────────────────────────
const mockGetOHLCV = vi.hoisted(() => vi.fn());

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getOHLCV: mockGetOHLCV })),
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

// ── Imports under test (AFTER mocks) ─────────────────────────────────────────
import { OHLCVChart } from "@/components/instrument/chart/OHLCVChart";
import { qk } from "@/lib/query/keys";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Synthetic ascending daily bars ending "today". */
function makeBars(count: number) {
  const DAY = 86_400_000;
  const end = Date.UTC(2026, 5, 9); // 2026-06-09
  return Array.from({ length: count }, (_, i) => ({
    timestamp: new Date(end - (count - 1 - i) * DAY).toISOString(),
    open: 100 + i,
    high: 101 + i,
    low: 99 + i,
    close: 100.5 + i,
    volume: 1_000_000 + i,
  }));
}

function renderChart(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <OHLCVChart instrumentId="ins-001" />
    </QueryClientProvider>,
  );
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetOHLCV.mockImplementation((id: string, params: { timeframe?: string }) =>
    Promise.resolve({
      instrument_id: id,
      ticker: "",
      timeframe: (params.timeframe ?? "1D").toUpperCase(),
      bars: makeBars(30),
    }),
  );
});

afterEach(() => cleanup());

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OHLCVChart period selector", () => {
  it("renders all 6 period pills with 1D selected by default", async () => {
    await act(async () => { renderChart(makeClient()); });
    for (const p of ["1D", "1W", "1M", "3M", "1Y", "5Y"]) {
      expect(screen.getByRole("button", { name: p })).toBeInTheDocument();
    }
    expect(
      screen.getByRole("button", { name: "1D" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("default 1D period fetches 5-minute bars with an explicit start date", async () => {
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    const [, params] = mockGetOHLCV.mock.calls[0];
    expect(params.timeframe).toBe("5M");
    // start is a date-only ISO string (see periodStartIso).
    expect(params.start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("selecting 1Y fetches daily bars (shared 1M/3M/1Y resolution)", async () => {
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    });
    await waitFor(() => {
      const calls = mockGetOHLCV.mock.calls.map(([, p]) => p.timeframe);
      expect(calls).toContain("1D");
    });
  });

  it("switching 1Y → 3M does NOT refetch (same daily-bar cache slot)", async () => {
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    });
    await waitFor(() => {
      expect(mockGetOHLCV.mock.calls.some(([, p]) => p.timeframe === "1D")).toBe(true);
    });
    const callsAfter1Y = mockGetOHLCV.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "3M" }));
    });
    // Same queryKey (qk.instruments.ohlcv(id, "1D")) + fresh data (staleTime
    // 5 min) → TanStack must serve from cache with ZERO additional fetches.
    expect(mockGetOHLCV.mock.calls.length).toBe(callsAfter1Y);
  });

  it("writes fetched bars into the shared qk.instruments.ohlcv cache slot", async () => {
    // Regression guard for the Round-1 key fix: QuoteTab's SessionStatsStrip
    // passively subscribes to this exact key — a bespoke key here silently
    // severs that data path (the pre-fix bug).
    const qc = makeClient();
    await act(async () => { renderChart(qc); });
    await waitFor(() => {
      const cached = qc.getQueryData<{ bars: unknown[] }>(
        qk.instruments.ohlcv("ins-001", "5M"),
      );
      expect(cached?.bars?.length).toBe(30);
    });
  });
});

describe("OHLCVChart crosshair legend", () => {
  it("shows OHLC+V for the hovered candle and hides on pointer-out", async () => {
    await act(async () => { renderChart(makeClient()); });
    // Wait for async chart init to wire the crosshair subscription.
    await waitFor(() => expect(h.subscribeCrosshairMove).toHaveBeenCalled());
    const handler = h.subscribeCrosshairMove.mock.calls[0][0] as (p: { time?: unknown }) => void;

    // Hover the LAST bar: its time is the epoch-seconds value the chart was
    // fed (Math.floor(ms / 1000)).
    const bars = makeBars(30);
    const lastSec = Math.floor(new Date(bars[bars.length - 1].timestamp).getTime() / 1000);
    await act(async () => { handler({ time: lastSec }); });

    const legend = await screen.findByTestId("crosshair-legend");
    // close = 100.5 + 29 = 129.50 for the last synthetic bar.
    expect(legend.textContent).toContain("129.50");

    // Pointer leaves the pane → param.time undefined → legend unmounts.
    await act(async () => { handler({ time: undefined }); });
    expect(screen.queryByTestId("crosshair-legend")).not.toBeInTheDocument();
  });
});
