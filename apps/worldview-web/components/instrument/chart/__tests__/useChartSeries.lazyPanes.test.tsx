/**
 * components/instrument/chart/__tests__/useChartSeries.lazyPanes.test.tsx
 *
 * WHY THIS EXISTS (Wave-2 pane rebuild, 2026-06-10): pins the HOOK-level
 * lifecycle of lazy oscillator panes through React renders:
 *
 *   1. Mount with all oscillators disabled → exactly ONE pane (price). The
 *      regression guard for the "5 permanent empty panes" broken chart.
 *   2. Enabling RSI via a prop flip → pane created + height pinned + the
 *      cached bars fed (the indicator paints without waiting for new data).
 *   3. Disabling RSI → chart.removePane fired and the pane gone.
 *
 * The factory-level pane mechanics live in createChartSeries.panes.test.ts;
 * this file tests the React reconciliation glue (effects, refs, ordering).
 *
 * MOCK STRATEGY: mock the lightweight-charts module with the same
 * v5-pane-semantics fake used by the factory test (panes() starts with the
 * price pane; 3-arg addSeries auto-creates panes).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { useMemo, useRef, act } from "react";
import { render, cleanup, waitFor } from "@testing-library/react";

// ── Mock: lightweight-charts (hoisted fake with v5 pane semantics) ───────────

const h = vi.hoisted(() => {
  interface FakePane {
    setHeight: ReturnType<typeof vi.fn>;
    paneIndex: () => number;
  }
  const state = {
    panes: [] as FakePane[],
    addSeriesPaneArgs: [] as Array<number | undefined>,
    setDataCalls: 0,
    removePane: vi.fn(),
  };
  const makePane = (): FakePane => {
    const pane: FakePane = {
      setHeight: vi.fn(),
      paneIndex: () => state.panes.indexOf(pane),
    };
    return pane;
  };
  const createChart = vi.fn(() => {
    // Fresh pane stack per chart instance — price pane pre-exists (v5 parity).
    state.panes = [makePane()];
    return {
      addSeries: vi.fn((_def: unknown, _opts?: unknown, paneIndex?: number) => {
        state.addSeriesPaneArgs.push(paneIndex);
        if (paneIndex != null && paneIndex === state.panes.length) state.panes.push(makePane());
        return { setData: vi.fn(() => { state.setDataCalls += 1; }), applyOptions: vi.fn() };
      }),
      panes: vi.fn(() => state.panes),
      removePane: vi.fn((i: number) => { state.removePane(i); state.panes.splice(i, 1); }),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      timeScale: vi.fn(() => ({ scrollToRealTime: vi.fn(), setVisibleRange: vi.fn() })),
      applyOptions: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      unsubscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
    };
  });
  return { state, createChart };
});

vi.mock("lightweight-charts", () => ({
  createChart: h.createChart,
  CandlestickSeries: "CandlestickSeries",
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
}));

// Imports AFTER the mock so the hook resolves the fake on dynamic import.
// eslint-disable-next-line import/first
import { useChartSeries } from "@/components/instrument/chart/useChartSeries";
// eslint-disable-next-line import/first
import {
  createDefaultIndicatorState,
  type IndicatorId,
  type IndicatorConfig,
} from "@/lib/instrument-context";
// eslint-disable-next-line import/first
import type { OHLCVBar } from "@/types/api";

// ── Harness ──────────────────────────────────────────────────────────────────

/** 5 synthetic ascending daily bars — enough to exercise setData paths. */
function makeBars(): OHLCVBar[] {
  const DAY = 86_400_000;
  const end = Date.UTC(2026, 5, 9);
  return Array.from({ length: 5 }, (_, i) => ({
    timestamp: new Date(end - (4 - i) * DAY).toISOString(),
    open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 1_000 + i,
  }));
}

function Harness({ enabledIds }: { enabledIds: readonly IndicatorId[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isFullscreenRef = useRef(false);
  const logScaleRef = useRef(false);
  // Build the indicators record from defaults, flipping the requested ids on.
  // WHY useMemo on the joined key: a fresh object per render would re-fire
  // every effect; keying on the id list mirrors real state behaviour.
  const indicators = useMemo(() => {
    const rec: Record<IndicatorId, IndicatorConfig> = createDefaultIndicatorState();
    for (const id of enabledIds) rec[id] = { ...rec[id], enabled: true };
    return rec;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledIds.join(",")]);

  useChartSeries({
    containerRef,
    isFullscreen: false,
    isFullscreenRef,
    indicators,
    showVolume: true, showMA50: false, showMA200: false,
    showVolMA20: false, showVWAPLine: false,
    data: { bars: makeBars() },
    instrumentId: "ins-1",
    timeframe: "1D",
    logScaleRef,
    logScale: false,
    onVolumeProfileBuckets: () => { /* not under test */ },
  });

  return <div ref={containerRef} />;
}

beforeEach(() => {
  h.state.addSeriesPaneArgs.length = 0;
  h.state.setDataCalls = 0;
  h.state.removePane.mockClear();
  h.createChart.mockClear();
});
afterEach(() => cleanup());

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useChartSeries lazy oscillator panes", () => {
  it("mounts with ONE pane when all oscillators are disabled (regression guard)", async () => {
    await act(async () => { render(<Harness enabledIds={[]} />); });
    await waitFor(() => expect(h.createChart).toHaveBeenCalled());
    // Price pane only — the broken chart had 6 panes here.
    expect(h.state.panes.length).toBe(1);
    // And no series was registered with an explicit pane index.
    expect(h.state.addSeriesPaneArgs.every((p) => p === undefined)).toBe(true);
  });

  it("enabling RSI creates its pane, pins the height, and feeds cached bars", async () => {
    const view = await act(async () => render(<Harness enabledIds={[]} />));
    await waitFor(() => expect(h.createChart).toHaveBeenCalled());
    const dataCallsBefore = h.state.setDataCalls;

    await act(async () => { view.rerender(<Harness enabledIds={["RSI"]} />); });

    await waitFor(() => expect(h.state.panes.length).toBe(2));
    // The pane height was pinned via the REAL setHeight API.
    expect(h.state.panes[1].setHeight).toHaveBeenCalled();
    // The RSI series received data immediately (fed from formattedBarsRef —
    // no wait for a refetch). setData count strictly increased.
    expect(h.state.setDataCalls).toBeGreaterThan(dataCallsBefore);
    // The series was created WITH a pane index (the lazy 3-arg overload).
    expect(h.state.addSeriesPaneArgs).toContain(1);
  });

  it("disabling RSI removes its pane via chart.removePane", async () => {
    const view = await act(async () => render(<Harness enabledIds={["RSI"]} />));
    await waitFor(() => expect(h.state.panes.length).toBe(2));

    await act(async () => { view.rerender(<Harness enabledIds={[]} />); });

    await waitFor(() => expect(h.state.panes.length).toBe(1));
    expect(h.state.removePane).toHaveBeenCalledWith(1);
  });

  it("an indicator persisted as enabled BEFORE init gets its pane after async init", async () => {
    // The localStorage-persisted case: indicators arrive enabled on mount,
    // but the chart initialises asynchronously (dynamic import). The
    // isChartReady dependency must replay the sync once the chart exists.
    await act(async () => { render(<Harness enabledIds={["MACD"]} />); });
    await waitFor(() => expect(h.state.panes.length).toBe(2));
    // MACD = 3 series, all in pane 1.
    expect(h.state.addSeriesPaneArgs.filter((p) => p === 1)).toHaveLength(3);
  });
});
