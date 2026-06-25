/**
 * components/instrument/chart/useChartSeries.ts — lightweight-charts series management hook
 *
 * Manages: chart init, core (pane-0) series refs, LAZY oscillator panes,
 * data-update effect, and visibility effects. Series creation is delegated to
 * createChartSeries.ts (plain factories — independently unit-testable).
 *
 * ── 2026-06-10 PANE REBUILD ──────────────────────────────────────────────────
 * The previous version created 5 permanent oscillator panes at init and tried
 * to hide them with a non-existent `pane.setOptions({height})` API (silent
 * no-op via optional chaining) — producing the broken "thin candles band +
 * three giant empty panes + floating 0.00 axis" chart. The rebuild:
 *
 *   - init creates ONLY pane-0 series (price + volume overlay + MA/BB/VWAP):
 *     the price chart owns the full canvas by default;
 *   - enabling an oscillator (RSI/MACD/ATR/STOCH/OBV) lazily creates its pane
 *     via createOscillatorSeries() and feeds it data from the bars cached in
 *     `formattedBarsRef`;
 *   - disabling it calls chart.removePane() (which DOES exist in v5.2.0,
 *     contrary to the old comment) so the price pane reclaims the space.
 *
 * PLAN REFERENCE: PRD-0088 Quote-tab redesign Wave 2 | WHO USES IT: OHLCVChart.tsx
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import {
  createCoreSeries,
  createOscillatorSeries,
  removeOscillatorPane,
  type CoreSeriesHandles,
  type OscillatorHandles,
  type OscillatorId,
  type SeriesDefs,
} from "@/components/instrument/chart/createChartSeries";
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
  type IndicatorId,
  type IndicatorConfig,
  type FormattedBar,
  type VolumeProfileBucket,
} from "@/lib/instrument-context";
import { CHART_HEIGHT, CHART_THEME, computeMA, toTime, setSeriesData } from "@/lib/chart-adapter";
import type { OHLCVBar } from "@/types/api";

/**
 * CoordinateConverter — minimal surface needed for price↔pixel mapping.
 * Kept for API compatibility with OHLCVChart (legacy DrawingCanvas interface).
 */
export interface CoordinateConverter {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  series: any;
}

// ── Props / Return types ──────────────────────────────────────────────────────

export interface UseChartSeriesOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  isFullscreen: boolean;
  isFullscreenRef: React.MutableRefObject<boolean>;
  indicators: Record<IndicatorId, IndicatorConfig>;
  showVolume: boolean;
  showMA50: boolean;
  showMA200: boolean;
  showVolMA20: boolean;
  showVWAPLine: boolean;
  data: { bars: OHLCVBar[] } | undefined;
  instrumentId: string;
  timeframe: string;
  logScaleRef: React.MutableRefObject<boolean>;
  logScale: boolean;
  onVolumeProfileBuckets: (buckets: VolumeProfileBucket[]) => void;
}

export interface UseChartSeriesReturn {
  chartRef: React.MutableRefObject<IChartApi | null>;
  seriesRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  volumeSeriesRef: React.MutableRefObject<ISeriesApi<"Histogram"> | null>;
  compareSeriesRef: React.MutableRefObject<ISeriesApi<"Line"> | null>;
  converters: CoordinateConverter | null;
  isChartReady: boolean;
  chartError: boolean;
}

// ── Oscillator data feed ──────────────────────────────────────────────────────
//
// WHY a plain function (module scope): feeding data into an oscillator's
// series happens from TWO places — the lazy-create path (user toggles RSI on
// after bars loaded) and the data-update effect (new bars arrive while RSI is
// live). One function guarantees the two paths can never drift.
//
// The `lines` array ordering matches createOscillatorSeries: MACD registers
// [histogram, line, signal]; STOCH registers [%K, %D]; the rest are single.

function feedOscillator(handles: OscillatorHandles, bars: FormattedBar[]): void {
  switch (handles.id) {
    case "RSI":
      setSeriesData(handles.lines[0] as ISeriesApi<"Line">, computeRSI(bars, 14));
      break;
    case "MACD": {
      const macd = computeMACD(bars, 12, 26, 9);
      setSeriesData(
        handles.lines[0] as ISeriesApi<"Histogram">,
        macd.map((d) => ({
          time: d.time, value: d.histogram,
          // Green above zero, red below — the universal MACD histogram cue.
          color: d.histogram >= 0 ? "#26A69A80" : "#EF535080",
        })),
      );
      setSeriesData(handles.lines[1] as ISeriesApi<"Line">, macd.map((d) => ({ time: d.time, value: d.macd })));
      setSeriesData(handles.lines[2] as ISeriesApi<"Line">, macd.map((d) => ({ time: d.time, value: d.signal })));
      break;
    }
    case "ATR":
      setSeriesData(handles.lines[0] as ISeriesApi<"Line">, computeATR(bars, 14));
      break;
    case "STOCHASTIC": {
      const stoch = computeStochastic(bars, 14, 3, 3);
      setSeriesData(handles.lines[0] as ISeriesApi<"Line">, stoch.map((d) => ({ time: d.time, value: d.k })));
      setSeriesData(handles.lines[1] as ISeriesApi<"Line">, stoch.map((d) => ({ time: d.time, value: d.d })));
      break;
    }
    case "OBV":
      setSeriesData(handles.lines[0] as ISeriesApi<"Line">, computeOBV(bars));
      break;
  }
}

/** The pane-hosted indicator subset of IndicatorId (VWAP is a pane-0 overlay). */
const OSCILLATOR_IDS: readonly OscillatorId[] = ["RSI", "MACD", "ATR", "STOCHASTIC", "OBV"];

// ── Memoized chart-library import ─────────────────────────────────────────────
//
// WHY a module-scope singleton promise (Wave-3 orphan-chart fix, 2026-06-11):
// React StrictMode mounts effects twice in dev, so chart init issues TWO
// dynamic `import("lightweight-charts")` calls concurrently. A real browser
// dedupes those to one module record, but module runners are not obliged to —
// vitest 2.x's mock interception, for one, returns the REAL module to the
// second concurrent request (bypassing vi.mock). One shared promise means one
// request in every environment: deterministic tests, marginally faster
// remounts, and no double network fetch of the chunk on slow connections.
let chartLibPromise: Promise<typeof import("lightweight-charts")> | null = null;

function loadChartLib(): Promise<typeof import("lightweight-charts")> {
  // WHY clear on rejection: a transient chunk-load failure (flaky network)
  // must not poison every future mount with a cached rejected promise — the
  // next mount retries the import from scratch.
  chartLibPromise ??= import("lightweight-charts").catch((err: unknown) => {
    chartLibPromise = null;
    throw err;
  });
  return chartLibPromise;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChartSeries({
  containerRef, isFullscreen, isFullscreenRef, indicators,
  showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
  data, instrumentId, timeframe, logScaleRef, logScale,
  onVolumeProfileBuckets,
}: UseChartSeriesOptions): UseChartSeriesReturn {

  // ── Chart + core series refs ───────────────────────────────────────────────
  // WHY refs (not state): series handles are mutable; storing in state would
  // cause an infinite loop (setState → re-render → setData → setState).
  const chartRef = useRef<IChartApi | null>(null);
  const coreRef = useRef<CoreSeriesHandles | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const compareSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // ── Lazy oscillator state ──────────────────────────────────────────────────
  // Map of LIVE oscillator panes. An entry exists ⟺ the pane exists on the
  // chart. Created/destroyed by the sync effect below.
  const oscRef = useRef<Partial<Record<OscillatorId, OscillatorHandles>>>({});
  // Resolved series-definition constants from the dynamic import — needed by
  // the lazy-create path long after init.
  const defsRef = useRef<SeriesDefs | null>(null);
  // Latest filtered/formatted bars — the lazy-create path feeds a freshly
  // created pane from here without waiting for the next data-update effect.
  const formattedBarsRef = useRef<FormattedBar[]>([]);

  // ── State returned to parent ───────────────────────────────────────────────
  const [converters, setConverters] = useState<CoordinateConverter | null>(null);
  // isChartReady: triggers data-update effect re-run if bars arrived before async init (BP-450)
  const [isChartReady, setIsChartReady] = useState(false);
  const [chartError, setChartError] = useState(false);
  // hasScrolledToRealTime: scroll fires ONCE per instrument+timeframe; bg refetches must not snap (BP-376)
  const hasScrolledToRealTime = useRef(false);
  const pendingScrollToRealTime = useRef(false);

  // Reset scroll guard on instrument/timeframe change
  useEffect(() => {
    hasScrolledToRealTime.current = false;
    pendingScrollToRealTime.current = false;
  }, [instrumentId, timeframe]);

  // ── Chart init & cleanup ───────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    let chart: IChartApi | null = null;
    // WHY a disposed flag (Wave-3 orphan-chart fix, 2026-06-11): the cleanup
    // below can run BEFORE the async import resolves (React StrictMode's
    // mount→unmount→remount in dev; fast tab switches in prod). The old
    // `!containerRef.current` guard does NOT catch the StrictMode case —
    // React re-attaches the ref on remount, so the STALE initChart from the
    // first mount saw a live container and created a second, orphaned chart
    // on the same node (an empty canvas stacked above the real one — the
    // "chart fills the slot but shows no candles" dev symptom). The flag is
    // scoped per effect instance, so a cancelled init can never attach.
    let disposed = false;

    async function initChart() {
      try {
        const { createChart, CandlestickSeries, LineSeries, HistogramSeries } =
          await loadChartLib();

        // WHY both checks after await: `disposed` covers cleanup-before-import
        // (StrictMode remount); the ref null-check covers a genuine unmount.
        if (disposed || !containerRef.current) return;

        // WHY clientHeight || CHART_HEIGHT: QuoteTab places the chart inside a
        // `flex-1 min-h-0` slot; reading the live container height lets the
        // canvas fill the slot. CHART_HEIGHT is only the never-laid-out fallback.
        chart = createChart(containerRef.current, {
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || CHART_HEIGHT,
          layout: CHART_THEME.layout,
          grid: CHART_THEME.grid,
          crosshair: CHART_THEME.crosshair,
          rightPriceScale: { borderColor: "#111113" },
          timeScale: { borderColor: "#111113", timeVisible: true },
        });

        // Persist the resolved series definitions for the lazy oscillator path.
        defsRef.current = { LineSeries, HistogramSeries, CandlestickSeries } as SeriesDefs;

        // PANE REBUILD: register pane-0 series ONLY. No oscillator panes are
        // created here — they are created lazily by the sync effect when (and
        // only when) the user enables them. This is what fixes the "empty
        // panes eat the viewport" bug.
        const core = createCoreSeries(chart, defsRef.current);
        chartRef.current = chart;
        coreRef.current = core;
        seriesRef.current = core.series;
        volumeSeriesRef.current = core.volumeSeries;

        setIsChartReady(true); // signals data-update + osc-sync effects to re-run (BP-450)
        chart.priceScale("right").applyOptions({ mode: logScaleRef.current ? 1 : 0 });
        setConverters({ chart, series: core.series });
        if (pendingScrollToRealTime.current) {
          pendingScrollToRealTime.current = false;
          // WHY assign flag AFTER scrollToRealTime (T-B-01 scroll-to-1985 fix):
          // the flag must only record a scroll that actually ran against the
          // real bar dataset — see BP-376.
          chart.timeScale().scrollToRealTime();
          hasScrolledToRealTime.current = true;
        }
      } catch (err) {
        console.error("Failed to load chart library:", err);
        setChartError(true);
      }
    }

    void initChart();

    // WHY track height as well as width: the chart canvas must mirror its
    // flex slot as the viewport resizes (PLAN-0090 Y-axis scaling fix).
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current && !isFullscreenRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || CHART_HEIGHT,
        });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      disposed = true; // cancel any in-flight initChart (see flag rationale above)
      observer.disconnect();
      // chart.remove() destroys every pane + series — no per-series cleanup needed.
      chart?.remove();
      chartRef.current = null;
      coreRef.current = null;
      seriesRef.current = null;
      volumeSeriesRef.current = null;
      compareSeriesRef.current = null;
      oscRef.current = {};
      defsRef.current = null;
      setConverters(null);
    };
    // WHY empty deps + disable: chart init must run exactly ONCE per mount —
    // re-running on indicators/ref identity changes would destroy and
    // recreate the canvas (visible flash). The refs the effect reads are
    // stable by construction; `indicators` is intentionally read lazily by
    // the per-oscillator sync effects below, never by init.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Update chart data when bars change ────────────────────────────────────
  useEffect(() => {
    const core = coreRef.current;
    if (!core || !data?.bars) return;

    // Round-4 hardening (item 1d): drop bars whose OHLC legs are not finite
    // numbers BEFORE they reach lightweight-charts. A degraded ingest row
    // carrying null/NaN crashes the candlestick autoscale and poisons every
    // derived indicator. OHLCVChart separately renders a named "not enough
    // data" state when <2 bars survive.
    const formattedBars: FormattedBar[] = data.bars
      .filter(
        (bar) =>
          Number.isFinite(bar.open) && Number.isFinite(bar.high) &&
          Number.isFinite(bar.low) && Number.isFinite(bar.close) &&
          // An unparseable timestamp would produce a NaN time key, which
          // lightweight-charts rejects with a hard throw.
          Number.isFinite(new Date(bar.timestamp).getTime()),
      )
      .map((bar) => ({
        time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
        open: bar.open, high: bar.high, low: bar.low, close: bar.close,
        // WHY finite guard: volume is the one leg that may be honestly null
        // (some venues omit it); zero renders as "no volume bar".
        volume: Number.isFinite(bar.volume) ? bar.volume : 0,
      }));

    // Cache for the lazy oscillator path (toggle-on after data already loaded).
    formattedBarsRef.current = formattedBars;

    // ── Core pane-0 series ───────────────────────────────────────────────────
    setSeriesData(core.series, formattedBars);
    // Volume: per-bar color (up=transparent green, down=transparent red)
    setSeriesData(core.volumeSeries, formattedBars.map((bar) => ({
      time: bar.time, value: bar.volume,
      color: bar.close >= bar.open ? "#26A69A40" : "#EF535040",
    })));
    setSeriesData(core.ma50Series, computeMA(formattedBars, 50));
    setSeriesData(core.ma200Series, computeMA(formattedBars, 200));

    const bbData = computeBollinger(formattedBars, 20, 2);
    setSeriesData(core.bbUpper, bbData.map((d) => ({ time: d.time, value: d.upper })));
    setSeriesData(core.bbMiddle, bbData.map((d) => ({ time: d.time, value: d.middle })));
    setSeriesData(core.bbLower, bbData.map((d) => ({ time: d.time, value: d.lower })));

    const vwapData = computeVWAP(formattedBars);
    setSeriesData(core.vwapSeries, vwapData);
    setSeriesData(core.vwapLineSeries, vwapData);
    setSeriesData(core.volMA20Series, computeVolumeMA(formattedBars, 20));
    onVolumeProfileBuckets(computeVolumeProfile(formattedBars, 24));

    // ── Live oscillator panes (only the ones the user has enabled) ──────────
    // WHY iterate the ref map (not `indicators`): the map is the source of
    // truth for which panes EXIST; the sync effect below reconciles it with
    // the `indicators` prop. Feeding only live panes means disabled
    // oscillators cost zero compute (the old code computed all 6 every time).
    for (const handles of Object.values(oscRef.current)) {
      if (handles) feedOscillator(handles, formattedBars);
    }

    // Scroll to right edge on first load only (BP-376) — flag assigned AFTER
    // the scroll actually runs (scroll-to-1985 fix).
    if (formattedBars.length > 0 && !hasScrolledToRealTime.current) {
      if (chartRef.current) { chartRef.current.timeScale().scrollToRealTime(); hasScrolledToRealTime.current = true; }
      else { pendingScrollToRealTime.current = true; }
    }
  // isChartReady in deps: re-fires after async init if bars arrived early (BP-450)
  }, [data?.bars, isChartReady, onVolumeProfileBuckets]);

  // ── Oscillator pane reconciliation ────────────────────────────────────────
  //
  // syncOscillator — create or destroy ONE oscillator pane so the chart
  // matches `indicators[id].enabled`. Idempotent: calling it when the chart
  // already matches is a no-op.
  const syncOscillator = useCallback((id: OscillatorId, enabled: boolean) => {
    const chart = chartRef.current;
    const defs = defsRef.current;
    if (!chart || !defs) return; // chart not initialised yet — the isChartReady effect below re-runs us
    const live = oscRef.current[id];

    if (enabled && !live) {
      // Toggle ON: create the pane + series, then feed it the cached bars so
      // the indicator paints immediately (no wait for the next data effect).
      const handles = createOscillatorSeries(chart, defs, id);
      oscRef.current[id] = handles;
      if (formattedBarsRef.current.length > 0) {
        feedOscillator(handles, formattedBarsRef.current);
      }
    } else if (!enabled && live) {
      // Toggle OFF: destroy the pane — the price pane reclaims the height.
      removeOscillatorPane(chart, live);
      delete oscRef.current[id];
    }
  }, []);

  // One effect per oscillator: each re-runs ONLY when its own enabled flag
  // flips (or when the chart finishes async init — isChartReady covers the
  // "user had RSI persisted in localStorage before the chart existed" case).
  useEffect(() => { syncOscillator("RSI", indicators.RSI.enabled); },
    [indicators.RSI.enabled, isChartReady, syncOscillator]);
  useEffect(() => { syncOscillator("MACD", indicators.MACD.enabled); },
    [indicators.MACD.enabled, isChartReady, syncOscillator]);
  useEffect(() => { syncOscillator("ATR", indicators.ATR.enabled); },
    [indicators.ATR.enabled, isChartReady, syncOscillator]);
  useEffect(() => { syncOscillator("STOCHASTIC", indicators.STOCHASTIC.enabled); },
    [indicators.STOCHASTIC.enabled, isChartReady, syncOscillator]);
  useEffect(() => { syncOscillator("OBV", indicators.OBV.enabled); },
    [indicators.OBV.enabled, isChartReady, syncOscillator]);

  // Defensive: if the OSCILLATOR_IDS list and the effects above ever drift,
  // fail loudly in dev rather than silently leaking a pane.
  if (process.env.NODE_ENV !== "production" && OSCILLATOR_IDS.length !== 5) {
    throw new Error("OSCILLATOR_IDS drifted from the per-oscillator effects");
  }

  // ── Pane-0 overlay visibility toggles ─────────────────────────────────────
  // These series live on pane 0 permanently; `visible` is the correct toggle
  // (no pane bookkeeping needed — they never create panes).
  useEffect(() => { coreRef.current?.volumeSeries.applyOptions({ visible: showVolume }); }, [showVolume]);
  useEffect(() => { coreRef.current?.ma50Series.applyOptions({ visible: showMA50 }); }, [showMA50]);
  useEffect(() => { coreRef.current?.ma200Series.applyOptions({ visible: showMA200 }); }, [showMA200]);
  useEffect(() => {
    const e = indicators.BOLLINGER.enabled;
    coreRef.current?.bbUpper.applyOptions({ visible: e });
    coreRef.current?.bbMiddle.applyOptions({ visible: e });
    coreRef.current?.bbLower.applyOptions({ visible: e });
  }, [indicators.BOLLINGER.enabled]);
  useEffect(() => { coreRef.current?.vwapSeries.applyOptions({ visible: indicators.VWAP.enabled }); }, [indicators.VWAP.enabled]);
  useEffect(() => { coreRef.current?.volMA20Series.applyOptions({ visible: showVolMA20 }); }, [showVolMA20]);
  useEffect(() => { coreRef.current?.vwapLineSeries.applyOptions({ visible: showVWAPLine }); }, [showVWAPLine]);

  // Log-scale (mode 0=Normal, 1=Logarithmic) and fullscreen resize
  useEffect(() => {
    chartRef.current?.priceScale("right").applyOptions({ mode: logScale ? 1 : 0 });
  }, [logScale]);
  useEffect(() => {
    if (!chartRef.current || !containerRef.current) return;
    // WHY clientHeight || CHART_HEIGHT on fullscreen EXIT: the container div's
    // own size never changed (only the canvas), so the ResizeObserver does not
    // fire — mirror the init-path logic and read the live container height.
    chartRef.current.applyOptions(isFullscreen
      ? { width: window.innerWidth, height: window.innerHeight - 60 }
      : {
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || CHART_HEIGHT,
        });
  }, [isFullscreen, containerRef]);

  return { chartRef, seriesRef, volumeSeriesRef, compareSeriesRef, converters, isChartReady, chartError };
}
