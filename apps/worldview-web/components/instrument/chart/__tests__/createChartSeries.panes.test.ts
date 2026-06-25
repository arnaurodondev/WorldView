/**
 * components/instrument/chart/__tests__/createChartSeries.panes.test.ts
 *
 * WHY THIS EXISTS (Wave-2 pane rebuild, 2026-06-10): the broken-chart bug —
 * a thin candle band at the top with three giant empty panes below — was
 * caused by 5 oscillator panes being created unconditionally at init and
 * "collapsed" with a NON-EXISTENT `pane.setOptions({height})` API (silent
 * no-op via optional chaining; the real v5 API is `pane.setHeight()`, and
 * heights are clamped to a 30px minimum anyway). These tests pin the rebuilt
 * contract:
 *
 *   1. createCoreSeries registers ONLY pane-0 series — it never passes a
 *      paneIndex to addSeries and never creates a pane. The price chart owns
 *      the full canvas by default (THE regression guard for the bug).
 *   2. createOscillatorSeries lazily creates the pane via the typed
 *      3-argument addSeries overload at index panes().length, and pins the
 *      pane height with the REAL setHeight API.
 *   3. removeOscillatorPane removes by the pane's LIVE index (paneIndex()),
 *      so removing pane A before pane B still removes the right pane.
 *
 * MOCK STRATEGY: a minimal fake chart that mirrors the v5 pane semantics —
 * panes() starts with [pane0]; addSeries(def, opts, idx) auto-creates a pane
 * when idx === panes().length (exactly what the real library does).
 */

import { describe, it, expect, vi } from "vitest";
import type { IChartApi } from "lightweight-charts";
import {
  createCoreSeries,
  createOscillatorSeries,
  removeOscillatorPane,
  OSC_PANE_HEIGHT,
  type SeriesDefs,
} from "@/components/instrument/chart/createChartSeries";

// ── Fake chart (v5 pane semantics) ───────────────────────────────────────────

interface FakePane {
  setHeight: ReturnType<typeof vi.fn>;
  paneIndex: () => number;
}

function makeFakeChart() {
  // panes[0] is the price pane — exists from chart creation, like the real lib.
  const panes: FakePane[] = [];
  const makePane = (): FakePane => {
    const pane: FakePane = {
      setHeight: vi.fn(),
      // WHY indexOf (not a captured number): removal shifts indexes; the real
      // IPaneApi.paneIndex() is live, so the fake must be too.
      paneIndex: () => panes.indexOf(pane),
    };
    return pane;
  };
  panes.push(makePane());

  const addSeriesCalls: Array<{ paneIndex: number | undefined }> = [];
  const chart = {
    addSeries: vi.fn((_def: unknown, _opts?: unknown, paneIndex?: number) => {
      addSeriesCalls.push({ paneIndex });
      // Mirror the real library: addSeries with paneIndex === panes.length
      // auto-creates the pane.
      if (paneIndex != null && paneIndex === panes.length) panes.push(makePane());
      return { setData: vi.fn(), applyOptions: vi.fn() };
    }),
    panes: vi.fn(() => panes),
    removePane: vi.fn((i: number) => { panes.splice(i, 1); }),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  };
  return { chart: chart as unknown as IChartApi, panes, addSeriesCalls, raw: chart };
}

// The defs are opaque tokens to the factories — strings suffice for the fake.
const DEFS = {
  LineSeries: "LineSeries",
  HistogramSeries: "HistogramSeries",
  CandlestickSeries: "CandlestickSeries",
} as unknown as SeriesDefs;

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("createCoreSeries (pane-0 only — THE empty-panes regression guard)", () => {
  it("never passes a paneIndex and never creates an extra pane", () => {
    const { chart, panes, addSeriesCalls } = makeFakeChart();
    createCoreSeries(chart, DEFS);

    // Every core series registers on the default pane — 3rd arg always absent.
    expect(addSeriesCalls.length).toBeGreaterThan(0);
    for (const call of addSeriesCalls) {
      expect(call.paneIndex).toBeUndefined();
    }
    // Still exactly ONE pane (the price pane) after init — the old code left
    // 6 panes here, which is exactly the broken-chart screenshot.
    expect(panes.length).toBe(1);
  });

  it("registers the volume histogram as a pane-0 overlay on the 'volume' scale", () => {
    const { chart, raw } = makeFakeChart();
    createCoreSeries(chart, DEFS);
    // The volume scale gets bottom-band margins (overlay layout) — if this
    // regressed to a separate pane the priceScale call would disappear.
    expect(raw.priceScale).toHaveBeenCalledWith("volume");
  });
});

describe("createOscillatorSeries (lazy pane creation)", () => {
  it("creates the pane at panes().length and pins its height via setHeight", () => {
    const { chart, panes, addSeriesCalls } = makeFakeChart();
    const handles = createOscillatorSeries(chart, DEFS, "RSI");

    // RSI = single line series, created at pane index 1 (price pane is 0).
    expect(addSeriesCalls).toHaveLength(1);
    expect(addSeriesCalls[0].paneIndex).toBe(1);
    expect(panes.length).toBe(2);
    // The REAL v5 API — setHeight, not the phantom setOptions.
    expect(panes[1].setHeight).toHaveBeenCalledWith(OSC_PANE_HEIGHT);
    expect(handles.lines).toHaveLength(1);
  });

  it("MACD registers histogram + line + signal in ONE shared pane", () => {
    const { chart, panes, addSeriesCalls } = makeFakeChart();
    const handles = createOscillatorSeries(chart, DEFS, "MACD");

    expect(handles.lines).toHaveLength(3);
    // All three series target the same (new) pane index.
    expect(addSeriesCalls.map((c) => c.paneIndex)).toEqual([1, 1, 1]);
    // Only one pane was created for the three series.
    expect(panes.length).toBe(2);
  });

  it("a second oscillator stacks at the next index", () => {
    const { chart, panes } = makeFakeChart();
    createOscillatorSeries(chart, DEFS, "RSI");        // pane 1
    const macd = createOscillatorSeries(chart, DEFS, "MACD"); // pane 2
    expect(panes.length).toBe(3);
    expect(macd.pane.paneIndex()).toBe(2);
  });
});

describe("removeOscillatorPane (live-index removal)", () => {
  it("removes the pane and the price pane reclaims the space", () => {
    const { chart, panes, raw } = makeFakeChart();
    const rsi = createOscillatorSeries(chart, DEFS, "RSI");
    removeOscillatorPane(chart, rsi);
    expect(raw.removePane).toHaveBeenCalledWith(1);
    expect(panes.length).toBe(1); // back to price-pane-only
  });

  it("removing an EARLIER pane first still removes the right LATER pane", () => {
    // The stale-index trap: RSI at 1, MACD at 2. Remove RSI → MACD shifts to
    // index 1. A captured numeric index would now remove the wrong pane;
    // paneIndex() is live so the right one goes.
    const { chart, panes, raw } = makeFakeChart();
    const rsi = createOscillatorSeries(chart, DEFS, "RSI");
    const macd = createOscillatorSeries(chart, DEFS, "MACD");

    removeOscillatorPane(chart, rsi);
    expect(panes.length).toBe(2); // price + macd
    removeOscillatorPane(chart, macd);
    // Second removal targeted index 1 (MACD's POST-SHIFT position), not 2.
    expect(raw.removePane).toHaveBeenLastCalledWith(1);
    expect(panes.length).toBe(1);
  });
});
