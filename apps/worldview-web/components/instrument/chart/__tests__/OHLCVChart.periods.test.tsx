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
  // Wave-4: the default daily view windows by BAR COUNT via
  // setVisibleLogicalRange. Capture calls so the "~200 visible" test can assert
  // the opening logical window spans ~200 bars.
  const setVisibleLogicalRange = vi.fn();
  const scrollToRealTime = vi.fn();
  // Round-4 hardening (item 3e): track remove() so the dispose test can
  // assert the chart instance is torn down on unmount (no leaked instance).
  const remove = vi.fn();
  // Round-4 hardening (item 1d): capture every setData payload so the
  // null-OHLC filter test can assert non-finite bars never reach the library.
  const setDataCalls: unknown[][] = [];
  const timeScale = vi.fn(() => ({
    fitContent: vi.fn(),
    scrollToRealTime,
    setVisibleRange,
    timeToCoordinate: vi.fn(() => null),
    coordinateToTime: vi.fn(() => null),
    setVisibleLogicalRange,
  }));
  const addSeries = vi.fn(() => ({
    setData: vi.fn((d: unknown[]) => setDataCalls.push(d)),
    applyOptions: vi.fn(),
  }));
  const createChart = vi.fn(() => ({
    addSeries,
    addPane: vi.fn(() => ({ setOptions: vi.fn() })),
    panes: vi.fn(() => []),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    applyOptions: vi.fn(),
    timeScale,
    subscribeCrosshairMove,
    unsubscribeCrosshairMove: vi.fn(),
    remove,
    removeSeries: vi.fn(),
  }));
  return { createChart, addSeries, subscribeCrosshairMove, setVisibleRange, setVisibleLogicalRange, scrollToRealTime, remove, setDataCalls };
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
  // Round-4: reset the captured setData payloads between tests (the array is
  // a shared hoisted handle, so clearAllMocks doesn't empty it).
  h.setDataCalls.length = 0;
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
  it("renders all 8 supported period pills with 1Y selected by default", async () => {
    // 2026-06-15 LONG-RANGE RESTORE: the pill set is now
    // [1D,5D,1M,3M,6M,1Y,5Y,MAX]. The long horizons (5Y/MAX) were RE-ADDED once
    // S3 wired its daily→weekly ("1W") and daily→monthly ("1M") derive logic, so
    // those views are servable again. 5D (intraday) and 6M (daily) stay. The 1W
    // *period* button is NOT restored — it mapped to the sparse 1H resolution
    // (~10 bars/day); only the 5Y/MAX long horizons came back. 1Y remains the
    // dense daily default.
    await act(async () => { renderChart(makeClient()); });
    for (const p of ["1D", "5D", "1M", "3M", "6M", "1Y", "5Y", "MAX"]) {
      expect(screen.getByRole("button", { name: p })).toBeInTheDocument();
    }
    // The 1W period button must NOT be present (it mapped to sparse 1H bars).
    expect(screen.queryByRole("button", { name: "1W" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "1Y" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("selecting 5Y fetches WEEKLY (1W) derived bars", async () => {
    // 5Y maps to the derived "1W" resolution — switching to it must request
    // weekly bars (S3 aggregates daily→weekly at query time). The chart passes
    // the frontend uppercase convention "1W"; the gateway normalizes it to "1w".
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "5Y" }));
    });
    await waitFor(() => {
      const calls = mockGetOHLCV.mock.calls.map(([, p]) => p.timeframe);
      expect(calls).toContain("1W");
    });
  });

  it("selecting MAX fetches MONTHLY (1M) derived bars", async () => {
    // MAX maps to the derived "1M" (uppercase = monthly) resolution. The
    // gateway preserves "1M" as-is for S3's case-sensitive ONE_MONTH enum.
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "MAX" }));
    });
    await waitFor(() => {
      const calls = mockGetOHLCV.mock.calls.map(([, p]) => p.timeframe);
      expect(calls).toContain("1M");
    });
  });

  it("default period fetches DAILY bars with an explicit start + a high bar limit", async () => {
    // WAVE-4: the default daily view must request the full ~500-bar window, so
    // it passes an explicit limit (S3 caps at 200 without one). The old default
    // fetched 5-minute bars over 3 days — now it's daily bars over ~730 days.
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    const [, params] = mockGetOHLCV.mock.calls[0];
    expect(params.timeframe).toBe("1D");
    // start is a date-only ISO string (see periodStartIso).
    expect(params.start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // High limit so the daily window isn't truncated at S3's 200-bar default.
    expect(params.limit).toBeGreaterThanOrEqual(500);
  });

  it("opens with ~200 bars visible of the ~500 loaded (bar-count window)", async () => {
    // The default 1Y preset windows the visible range to the LAST 200 BARS via
    // setVisibleLogicalRange — independent of calendar-day span. With 500 loaded
    // bars the opening logical window must be [≈300, ≈500] (the last 200), so
    // there are ~300 bars of loaded history to pan back through. This is the
    // core "load 500, show 200" requirement.
    mockGetOHLCV.mockResolvedValue({
      instrument_id: "ins-001", ticker: "", timeframe: "1D", bars: makeBars(500),
    });
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(h.setVisibleLogicalRange).toHaveBeenCalled());
    // Find the windowing call (a logical range object with from/to indices).
    const call = h.setVisibleLogicalRange.mock.calls.at(-1)![0] as { from: number; to: number };
    const visibleSpan = call.to - call.from;
    // ~200 bars wide (allow the half-bar edge padding, so 199-201).
    expect(visibleSpan).toBeGreaterThanOrEqual(199);
    expect(visibleSpan).toBeLessThanOrEqual(201);
    // The window ends at the newest bar (right edge) and leaves ~300 loaded
    // bars to the left of `from` to pan into.
    expect(call.from).toBeGreaterThan(290);
    expect(call.to).toBeGreaterThan(498);
  });

  it("selecting 1D fetches 5-minute intraday bars", async () => {
    // Default is now 1Y (daily); switching to the 1D period must derive the 5M
    // intraday resolution. (Pre-Wave-4 this asserted the inverse direction.)
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(mockGetOHLCV).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "1D" }));
    });
    await waitFor(() => {
      const calls = mockGetOHLCV.mock.calls.map(([, p]) => p.timeframe);
      expect(calls).toContain("5M");
    });
  });

  it("switching 1Y → 3M does NOT refetch (same daily-bar cache slot)", async () => {
    // Default is 1Y (daily bars) — the very first fetch is already "1D".
    await act(async () => { renderChart(makeClient()); });
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
    // severs that data path (the pre-fix bug). WAVE-4: the default period is now
    // 1Y → "1D" resolution, so the shared slot key is ("ins-001", "1D").
    const qc = makeClient();
    await act(async () => { renderChart(qc); });
    await waitFor(() => {
      const cached = qc.getQueryData<{ bars: unknown[] }>(
        qk.instruments.ohlcv("ins-001", "1D"),
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

// ── Round-4 hardening tests ───────────────────────────────────────────────────

describe("OHLCVChart lifecycle (Round-4 item 3a/3e)", () => {
  it("creates exactly ONE chart instance across period switches in the shared slot", async () => {
    // 1M / 3M / 1Y share the daily-bar fetch and differ only by visible
    // range — switching among them must be a pure client-side re-window,
    // never a chart teardown/rebuild (which would flash + reset the GL ctx).
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(h.createChart).toHaveBeenCalledTimes(1));
    // Sequential explicit clicks (not a loop) — keeps the await chain flat
    // and silences no-await-in-loop without weakening the assertion.
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "1M" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "3M" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "1Y" })); });
    expect(h.createChart).toHaveBeenCalledTimes(1);
    expect(h.remove).not.toHaveBeenCalled();
  });

  it("disposes the chart instance on unmount (no leaked lightweight-charts instance)", async () => {
    let view: ReturnType<typeof renderChart>;
    await act(async () => { view = renderChart(makeClient()); });
    await waitFor(() => expect(h.createChart).toHaveBeenCalledTimes(1));
    await act(async () => { view!.unmount(); });
    // chart.remove() is the library's dispose — it also detaches the
    // internal listeners; the ResizeObserver is disconnected in the same
    // cleanup (see useChartSeries init-effect return).
    expect(h.remove).toHaveBeenCalledTimes(1);
  });
});

describe("OHLCVChart error recovery (Round-4 item 1b)", () => {
  it("renders a named per-section error with Retry when the OHLCV fetch fails", async () => {
    mockGetOHLCV.mockRejectedValue(new Error("S9 unavailable"));
    await act(async () => { renderChart(makeClient()); });
    // NAMED state — previously a failed fetch fell through every branch and
    // left a blank canvas surrounded by live toolbars.
    const errBox = await screen.findByTestId("chart-fetch-error");
    expect(errBox).toBeInTheDocument();
    // Retry refires the query: flip the gateway to success and click.
    mockGetOHLCV.mockImplementation((id: string) =>
      Promise.resolve({ instrument_id: id, ticker: "", timeframe: "5M", bars: makeBars(30) }),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    });
    await waitFor(() => {
      expect(screen.queryByTestId("chart-fetch-error")).not.toBeInTheDocument();
    });
  });
});

describe("OHLCVChart degraded-bars guards (Round-4 item 1d)", () => {
  it("renders the insufficient-data state when only one bar is plottable", async () => {
    // 1 valid bar + 2 all-null bars: length>0 so the legacy zero-bar state
    // does NOT apply, but <2 plottable bars cannot form price action.
    // WHY the unknown-cast: OHLCVBar TYPES the legs as number, but the wire
    // can deliver null — that type/wire gap is exactly what this test pins.
    const nul = null as unknown as number;
    const bars = makeBars(3).map((b, i) =>
      i === 0 ? b : { ...b, open: nul, high: nul, low: nul, close: nul },
    );
    mockGetOHLCV.mockResolvedValue({ instrument_id: "ins-001", ticker: "", timeframe: "5M", bars });
    await act(async () => { renderChart(makeClient()); });
    expect(await screen.findByTestId("chart-insufficient-data")).toBeInTheDocument();
  });

  it("filters non-finite OHLC bars before they reach lightweight-charts (no NaN crash)", async () => {
    // 30 valid bars with 2 poisoned rows interleaved — the candle series must
    // receive ONLY the 30 finite bars (NaN autoscale → blank canvas class).
    const good = makeBars(30);
    const nul = null as unknown as number; // wire null vs typed number — see above
    const poisoned = [
      ...good.slice(0, 10),
      { ...good[10], open: nul, high: nul, low: nul, close: nul },
      ...good.slice(10, 20),
      { ...good[20], close: Number.NaN },
      ...good.slice(20),
    ];
    mockGetOHLCV.mockResolvedValue({ instrument_id: "ins-001", ticker: "", timeframe: "5M", bars: poisoned });
    await act(async () => { renderChart(makeClient()); });
    await waitFor(() => expect(h.setDataCalls.length).toBeGreaterThan(0));
    // Every payload handed to ANY series must be NaN-free in its value legs.
    for (const payload of h.setDataCalls) {
      for (const point of payload as Array<Record<string, unknown>>) {
        for (const key of ["open", "high", "low", "close", "value"]) {
          if (key in point) {
            expect(Number.isFinite(point[key] as number)).toBe(true);
          }
        }
      }
    }
    // The candlestick payloads specifically must carry the 30 valid bars.
    const candles = h.setDataCalls.find((d) => (d[0] as Record<string, unknown> | undefined)?.open !== undefined);
    expect((candles ?? []).length).toBe(30);
  });
});

describe("OHLCVChart canvas a11y (Round-4 item 2)", () => {
  it("labels the chart wrapper with a latest-OHLC summary (role=img)", async () => {
    await act(async () => { renderChart(makeClient()); });
    const wrapper = await screen.findByTestId("chart-wrapper");
    expect(wrapper).toHaveAttribute("role", "img");
    await waitFor(() => {
      // Last synthetic bar: open 129, high 130, low 128, close 129.50.
      expect(wrapper.getAttribute("aria-label")).toContain("close 129.50");
    });
  });
});
