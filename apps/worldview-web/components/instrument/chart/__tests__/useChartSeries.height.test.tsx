/**
 * components/instrument/chart/__tests__/useChartSeries.height.test.tsx
 *
 * WHY THIS EXISTS (Wave-3 black-void fix, 2026-06-11): pins the THREE
 * behaviours that together caused / fix the "280px chart inside a 600px slot
 * with a giant black void below" bug on the Quote tab:
 *
 *   1. HEIGHT FOLLOWS CONTAINER — the ResizeObserver wired at init must apply
 *      BOTH width and height to the chart whenever the container resizes. The
 *      broken page had a circular measurement (the container's height WAS the
 *      canvas height), so this is the contract that keeps the canvas glued to
 *      its flex slot once OHLCVChart's CSS chain gives the container a real
 *      height.
 *
 *   2. VOL TOGGLE = OVERLAY VISIBILITY, NOT PANES — the "VOL 1" toolbar state
 *      was suspected of creating a separate volume pane (which at default
 *      stretch would split the canvas 50/50 and reproduce the void). Volume
 *      is a pane-0 OVERLAY: toggling it must flip `visible` on the volume
 *      series and never add/remove a pane.
 *
 *   3. STRICTMODE / FAST-UNMOUNT INIT RACE — chart init awaits a dynamic
 *      import; React StrictMode (dev) unmounts and remounts the component
 *      while that import is in flight. Without the `disposed` flag the STALE
 *      first init still attached a chart to the remounted node — an orphaned
 *      EMPTY canvas stacked above the real chart (full-height black canvas,
 *      no candles). Exactly one chart may ever attach per surviving mount.
 *
 * MOCK STRATEGY: same v5-pane-semantics fake as useChartSeries.lazyPanes
 * (panes() starts with the price pane; 3-arg addSeries auto-creates panes),
 * extended to record every created chart (for applyOptions assertions) and
 * every series' creation options (to identify the volume overlay). A
 * test-controlled ResizeObserver replaces the global no-op stub so tests can
 * fire resize callbacks deterministically.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React, { useMemo, useRef, useState, act } from "react";
import { render, cleanup, waitFor } from "@testing-library/react";

// ── Mock: lightweight-charts (hoisted fake with v5 pane semantics) ───────────

const h = vi.hoisted(() => {
  interface FakePane {
    setHeight: ReturnType<typeof vi.fn>;
    paneIndex: () => number;
  }
  interface FakeSeries {
    opts: Record<string, unknown> | undefined;
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
  }
  interface FakeChart {
    applyOptions: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
  }
  const state = {
    panes: [] as FakePane[],
    /** Every series created on the CURRENT chart, with its creation options. */
    series: [] as FakeSeries[],
    /** Every chart instance ever created — index 0 is the first. */
    charts: [] as FakeChart[],
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
    state.series = [];
    const chart = {
      addSeries: vi.fn((_def: unknown, opts?: Record<string, unknown>, paneIndex?: number) => {
        if (paneIndex != null && paneIndex === state.panes.length) state.panes.push(makePane());
        const series: FakeSeries = { opts, setData: vi.fn(), applyOptions: vi.fn() };
        state.series.push(series);
        return series;
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
    state.charts.push(chart);
    return chart;
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
import { createDefaultIndicatorState } from "@/lib/instrument-context";
// eslint-disable-next-line import/first
import type { OHLCVBar } from "@/types/api";

// ── Controllable ResizeObserver ───────────────────────────────────────────────
//
// WHY replace the global stub: vitest.setup.ts installs a NO-OP ResizeObserver
// (observe/disconnect do nothing, the callback never fires). These tests must
// DRIVE the callback to assert the resize → applyOptions contract, so each
// test run installs this recording fake instead.

interface RecordedObserver {
  callback: ResizeObserverCallback;
  observed: Element[];
  disconnected: boolean;
}
const recordedObservers: RecordedObserver[] = [];

class ControllableResizeObserver {
  private readonly record: RecordedObserver;
  constructor(callback: ResizeObserverCallback) {
    this.record = { callback, observed: [], disconnected: false };
    recordedObservers.push(this.record);
  }
  observe(el: Element): void { this.record.observed.push(el); }
  unobserve(): void { /* not exercised */ }
  disconnect(): void { this.record.disconnected = true; }
}

/** Fire every live (non-disconnected) observer callback once. */
function fireResize(): void {
  for (const rec of recordedObservers) {
    if (!rec.disconnected) {
      rec.callback([], undefined as unknown as ResizeObserver);
    }
  }
}

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

/** Imperative handle the tests use to flip showVolume from outside. */
interface HarnessHandle { setShowVolume: (v: boolean) => void }

function Harness({ handleRef }: { handleRef?: React.MutableRefObject<HarnessHandle | null> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isFullscreenRef = useRef(false);
  const logScaleRef = useRef(false);
  const [showVolume, setShowVolume] = useState(true);
  if (handleRef) handleRef.current = { setShowVolume };
  // Stable indicators record (all disabled) — fresh objects would re-fire effects.
  const indicators = useMemo(() => createDefaultIndicatorState(), []);

  useChartSeries({
    containerRef,
    isFullscreen: false,
    isFullscreenRef,
    indicators,
    showVolume, showMA50: false, showMA200: false,
    showVolMA20: false, showVWAPLine: false,
    data: { bars: makeBars() },
    instrumentId: "ins-1",
    timeframe: "1D",
    logScaleRef,
    logScale: false,
    onVolumeProfileBuckets: () => { /* not under test */ },
  });

  return <div ref={containerRef} data-testid="container" />;
}

/** jsdom always reports clientWidth/Height = 0 — pin real values on the node. */
function setContainerSize(el: Element, width: number, height: number): void {
  Object.defineProperty(el, "clientWidth", { value: width, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: height, configurable: true });
}

beforeEach(() => {
  h.state.panes.length = 0;
  h.state.series.length = 0;
  h.state.charts.length = 0;
  h.state.removePane.mockClear();
  h.createChart.mockClear();
  recordedObservers.length = 0;
  vi.stubGlobal("ResizeObserver", ControllableResizeObserver);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("useChartSeries height-follows-container (Wave-3 black-void fix)", () => {
  it("applies the container's NEW height (not just width) when the ResizeObserver fires", async () => {
    const view = await act(async () => render(<Harness />));
    await waitFor(() => expect(h.createChart).toHaveBeenCalledTimes(1));
    const chart = h.state.charts[0];
    const container = view.getByTestId("container");

    // The flex slot settles at 1024×480 after layout.
    setContainerSize(container, 1024, 480);
    await act(async () => { fireResize(); });
    expect(chart.applyOptions).toHaveBeenCalledWith({ width: 1024, height: 480 });

    // Viewport grows — the chart must track the slot UP...
    setContainerSize(container, 1024, 720);
    await act(async () => { fireResize(); });
    expect(chart.applyOptions).toHaveBeenCalledWith({ width: 1024, height: 720 });

    // ...and back DOWN (min-h-0 shrink path — the circular-measurement bug
    // showed up as the height never shrinking once content propped it open).
    setContainerSize(container, 1024, 300);
    await act(async () => { fireResize(); });
    expect(chart.applyOptions).toHaveBeenCalledWith({ width: 1024, height: 300 });
  });

  it("falls back to a non-zero height when the container measures 0 (never a 0px canvas)", async () => {
    const view = await act(async () => render(<Harness />));
    await waitFor(() => expect(h.createChart).toHaveBeenCalledTimes(1));
    const chart = h.state.charts[0];
    setContainerSize(view.getByTestId("container"), 800, 0);

    await act(async () => { fireResize(); });

    // clientHeight=0 (container not laid out yet) → CHART_HEIGHT fallback.
    const lastCall = chart.applyOptions.mock.calls.at(-1)?.[0] as { height: number };
    expect(lastCall.height).toBeGreaterThan(0);
  });
});

describe("useChartSeries VOL toggle pane accounting (Wave-3)", () => {
  it("toggling volume flips overlay visibility and NEVER adds/removes a pane", async () => {
    const handleRef: React.MutableRefObject<HarnessHandle | null> = { current: null };
    await act(async () => { render(<Harness handleRef={handleRef} />); });
    await waitFor(() => expect(h.createChart).toHaveBeenCalledTimes(1));

    // Volume is the only series created on the dedicated "volume" price scale
    // PLUS the volume-format flag — identify it by its creation options.
    const volumeSeries = h.state.series.find(
      (s) => s.opts?.priceScaleId === "volume" && (s.opts?.priceFormat as { type?: string } | undefined)?.type === "volume",
    );
    expect(volumeSeries).toBeDefined();
    expect(h.state.panes.length).toBe(1); // price pane only

    // VOL off → overlay hidden, pane count untouched.
    await act(async () => { handleRef.current?.setShowVolume(false); });
    expect(volumeSeries?.applyOptions).toHaveBeenCalledWith({ visible: false });
    expect(h.state.panes.length).toBe(1);
    expect(h.state.removePane).not.toHaveBeenCalled();

    // VOL back on → overlay visible again; still exactly one pane (no stray
    // pane with default stretch — the 50/50 split suspected in the void bug).
    await act(async () => { handleRef.current?.setShowVolume(true); });
    expect(volumeSeries?.applyOptions).toHaveBeenCalledWith({ visible: true });
    expect(h.state.panes.length).toBe(1);
  });
});

describe("useChartSeries StrictMode init race (Wave-3 orphan-chart fix)", () => {
  it("attaches exactly ONE chart under StrictMode double-mount (stale init is cancelled)", async () => {
    // StrictMode mounts → unmounts → remounts while the dynamic import is in
    // flight. The `disposed` flag must cancel the FIRST mount's init before
    // it calls createChart — otherwise an orphaned empty chart stacks above
    // the real one (the "full-height black canvas, no candles" dev symptom).
    await act(async () => {
      render(
        <React.StrictMode>
          <Harness />
        </React.StrictMode>,
      );
    });

    await waitFor(() => expect(h.createChart).toHaveBeenCalled());
    expect(h.createChart).toHaveBeenCalledTimes(1);
    // And the surviving chart was NOT torn down by the StrictMode cleanup.
    expect(h.state.charts[0].remove).not.toHaveBeenCalled();
  });
});
