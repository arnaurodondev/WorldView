/**
 * components/instrument/chart/useChartSeries.ts — lightweight-charts series management hook
 * Manages: chart init, all indicator series refs, data-update effect, visibility effects.
 * Series creation is delegated to createChartSeries.ts (plain async factory).
 * PLAN REFERENCE: PLAN-0089 Wave D-1 | WHO USES IT: OHLCVChart.tsx
 */

"use client";

import { useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { createAllChartSeries, PANE_HEIGHT_ENABLED, PANE_HEIGHT_DISABLED } from "@/components/instrument/chart/createChartSeries";

/**
 * CoordinateConverter — minimal surface needed for price↔pixel mapping.
 *
 * WHY INLINED HERE: PLAN-0090 T-E-01 deletes the legacy DrawingCanvas component
 * (PRD-0088 removes the drawing-tools workflow), so the interface that used to
 * live there is now defined locally. The struct is intentionally narrow — the
 * remaining chart code only needs the two refs to wire indicators into the
 * lightweight-charts series. If a future feature reintroduces price↔pixel math
 * outside this hook, promote this back to a shared types module.
 */
export interface CoordinateConverter {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  series: any;
}
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

// ── Props / Return types ───────────────────────────────────────────────────────

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
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ma200SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // ── Indicator series refs ──────────────────────────────────────────────────
  const rsiPaneRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const atrRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stochKRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stochDRef = useRef<ISeriesApi<"Line"> | null>(null);
  const obvRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);
  const volMA20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const compareSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

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

    async function initChart() {
      try {
        const { createChart, CandlestickSeries, LineSeries, HistogramSeries } =
          await import("lightweight-charts");

        // WHY null check after await: component may have unmounted during the import.
        if (!containerRef.current) return;

        // WHY clientHeight || CHART_HEIGHT (PLAN-0090 Y-axis scaling fix):
        // QuoteTab places the chart inside a `flex-1 min-h-0` slot that grows
        // to fill the left column (~600-800px). Hard-coding height=CHART_HEIGHT
        // (280px) made the chart render only in the top ~20% of its slot,
        // leaving the rest as empty container background with stray "0.00"
        // gridlines. Reading the live container height lets the chart canvas
        // match the slot. Fallback to CHART_HEIGHT if clientHeight is 0 (e.g.
        // the slot has not been laid out yet — never happened in testing).
        chart = createChart(containerRef.current, {
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || CHART_HEIGHT,
          layout: CHART_THEME.layout,
          grid: CHART_THEME.grid,
          crosshair: CHART_THEME.crosshair,
          rightPriceScale: { borderColor: "#111113" },
          timeScale: { borderColor: "#111113", timeVisible: true },
        });

        // Delegate all series creation to the factory — keeps this hook concise.
        // WHY pass `indicators`: the factory needs to know which panes to show
        // at height 80 vs height 0 on init (PLAN-0099 W4 lazy-pane fix).
        const handles = await createAllChartSeries(
          chart, LineSeries, HistogramSeries, CandlestickSeries, indicators,
        );

        // Assign all series handles to refs
        chartRef.current = chart;
        seriesRef.current = handles.series;
        volumeSeriesRef.current = handles.volumeSeries;
        ma50SeriesRef.current = handles.ma50Series;
        ma200SeriesRef.current = handles.ma200Series;
        rsiPaneRef.current = handles.rsiSeries;
        macdLineRef.current = handles.macdLine;
        macdSignalRef.current = handles.macdSignal;
        macdHistRef.current = handles.macdHist;
        bbUpperRef.current = handles.bbUpper;
        bbMiddleRef.current = handles.bbMiddle;
        bbLowerRef.current = handles.bbLower;
        atrRef.current = handles.atrSeries;
        stochKRef.current = handles.stochK;
        stochDRef.current = handles.stochD;
        obvRef.current = handles.obvSeries;
        vwapRef.current = handles.vwapSeries;
        volMA20Ref.current = handles.volMA20Series;
        vwapLineRef.current = handles.vwapLineSeries;

        setIsChartReady(true); // signals data-update effect re-run (BP-450)
        chart.priceScale("right").applyOptions({ mode: logScaleRef.current ? 1 : 0 });
        setConverters({ chart, series: handles.series });
        if (pendingScrollToRealTime.current) {
          pendingScrollToRealTime.current = false;
          // WHY assign flag AFTER scrollToRealTime (T-B-01 scroll-to-1985 fix):
          // setting flag=true BEFORE the call created a race in which a later
          // render observed flag=true but the scroll had not yet executed
          // against the real bar dataset → viewport stuck at the oldest bar
          // (e.g. 1985). Order swapped so the flag only records a scroll that
          // actually ran.
          chart.timeScale().scrollToRealTime();
          hasScrolledToRealTime.current = true;
        }
      } catch (err) {
        console.error("Failed to load chart library:", err);
        setChartError(true);
      }
    }

    void initChart();

    // WHY also track height (PLAN-0090 Y-axis scaling fix): previously only
    // width was synced, so when the parent flex slot was taller than 280px the
    // chart canvas stayed pinned at its initial height, leaving most of the
    // available vertical space blank. Mirroring height keeps the chart filling
    // its flex slot as it grows (e.g. on viewport resize / fullscreen toggle).
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
      observer.disconnect();
      chart?.remove();
      chartRef.current = null; seriesRef.current = null; volumeSeriesRef.current = null;
      ma50SeriesRef.current = null; ma200SeriesRef.current = null; rsiPaneRef.current = null;
      macdLineRef.current = null; macdSignalRef.current = null; macdHistRef.current = null;
      bbUpperRef.current = null; bbMiddleRef.current = null; bbLowerRef.current = null;
      atrRef.current = null; stochKRef.current = null; stochDRef.current = null;
      obvRef.current = null; vwapRef.current = null; volMA20Ref.current = null;
      vwapLineRef.current = null; compareSeriesRef.current = null;
      setConverters(null);
    };
  }, []); // empty deps: chart init runs once on mount, cleanup on unmount
  // eslint-disable-next-line react-hooks/exhaustive-deps

  // ── Update chart data when bars change ────────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current || !data?.bars) return;

    const formattedBars: FormattedBar[] = data.bars.map((bar) => ({
      time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
      open: bar.open, high: bar.high, low: bar.low, close: bar.close,
      volume: bar.volume ?? 0,
    }));

    setSeriesData(seriesRef.current, formattedBars);
    // Volume: per-bar color (up=transparent green, down=transparent red)
    setSeriesData(volumeSeriesRef.current, formattedBars.map((bar) => ({
      time: bar.time, value: bar.volume,
      color: bar.close >= bar.open ? "#26A69A40" : "#EF535040",
    })));
    setSeriesData(ma50SeriesRef.current, computeMA(formattedBars, 50));
    setSeriesData(ma200SeriesRef.current, computeMA(formattedBars, 200));
    // All indicators computed upfront: user can enable any without a refetch.
    setSeriesData(rsiPaneRef.current, computeRSI(formattedBars, 14));

    if (macdLineRef.current || macdSignalRef.current || macdHistRef.current) {
      const macdData = computeMACD(formattedBars, 12, 26, 9);
      setSeriesData(macdLineRef.current, macdData.map((d) => ({ time: d.time, value: d.macd })));
      setSeriesData(macdSignalRef.current, macdData.map((d) => ({ time: d.time, value: d.signal })));
      setSeriesData(macdHistRef.current, macdData.map((d) => ({
        time: d.time, value: d.histogram,
        color: d.histogram >= 0 ? "#26A69A80" : "#EF535080",
      })));
    }

    if (bbUpperRef.current || bbMiddleRef.current || bbLowerRef.current) {
      const bbData = computeBollinger(formattedBars, 20, 2);
      setSeriesData(bbUpperRef.current, bbData.map((d) => ({ time: d.time, value: d.upper })));
      setSeriesData(bbMiddleRef.current, bbData.map((d) => ({ time: d.time, value: d.middle })));
      setSeriesData(bbLowerRef.current, bbData.map((d) => ({ time: d.time, value: d.lower })));
    }

    setSeriesData(atrRef.current, computeATR(formattedBars, 14));
    if (stochKRef.current || stochDRef.current) {
      const stochData = computeStochastic(formattedBars, 14, 3, 3);
      setSeriesData(stochKRef.current, stochData.map((d) => ({ time: d.time, value: d.k })));
      setSeriesData(stochDRef.current, stochData.map((d) => ({ time: d.time, value: d.d })));
    }
    setSeriesData(obvRef.current, computeOBV(formattedBars));
    const vwapData = computeVWAP(formattedBars);
    setSeriesData(vwapRef.current, vwapData);
    setSeriesData(vwapLineRef.current, vwapData);
    setSeriesData(volMA20Ref.current, computeVolumeMA(formattedBars, 20));
    onVolumeProfileBuckets(computeVolumeProfile(formattedBars, 24));

    // Scroll to right edge on first load only (BP-376)
    // WHY assign flag AFTER scrollToRealTime (T-B-01 scroll-to-1985 fix):
    // the previous order set flag=true first, which on a fast re-render path
    // caused a subsequent invocation to short-circuit even though the
    // scroll-to-real-time had not yet executed against the loaded bars,
    // leaving the chart viewport pinned to the oldest bar (e.g. 1985).
    if (formattedBars.length > 0 && !hasScrolledToRealTime.current) {
      if (chartRef.current) { chartRef.current.timeScale().scrollToRealTime(); hasScrolledToRealTime.current = true; }
      else { pendingScrollToRealTime.current = true; }
    }
  // isChartReady in deps: re-fires after async init if bars arrived early (BP-450)
  }, [data?.bars, isChartReady, onVolumeProfileBuckets]);

  // ── Visibility toggle effects ──────────────────────────────────────────────
  //
  // WHY pane height toggling alongside series visibility (PLAN-0099 W4):
  // lightweight-charts v5 has no removePane() API — panes are permanent once
  // created. Setting series `visible: false` hides the line but leaves the
  // pane canvas (with its "0.00" axis label) visible. We also toggle the pane
  // height between PANE_HEIGHT_ENABLED (80px) and PANE_HEIGHT_DISABLED (0px)
  // so that disabled oscillator panes visually collapse to nothing.
  //
  // Each oscillator pane is at a fixed index: RSI=1, MACD=2, ATR=3, STOCH=4, OBV=5.
  // We cast chart.panes()[N] as `any` because the IChartApi typings don't expose
  // the pane-level setOptions() method (runtime-only extension in v5).
  useEffect(() => { volumeSeriesRef.current?.applyOptions({ visible: showVolume }); }, [showVolume]);
  useEffect(() => { ma50SeriesRef.current?.applyOptions({ visible: showMA50 }); }, [showMA50]);
  useEffect(() => { ma200SeriesRef.current?.applyOptions({ visible: showMA200 }); }, [showMA200]);
  useEffect(() => {
    const e = indicators.RSI.enabled;
    rsiPaneRef.current?.applyOptions({ visible: e });
    // Collapse / expand the RSI pane so it doesn't show "0.00" when hidden.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chartRef.current?.panes?.()[1] as any)?.setOptions?.({ height: e ? PANE_HEIGHT_ENABLED : PANE_HEIGHT_DISABLED });
  }, [indicators.RSI.enabled]);
  useEffect(() => {
    const e = indicators.MACD.enabled;
    macdLineRef.current?.applyOptions({ visible: e });
    macdSignalRef.current?.applyOptions({ visible: e });
    macdHistRef.current?.applyOptions({ visible: e });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chartRef.current?.panes?.()[2] as any)?.setOptions?.({ height: e ? PANE_HEIGHT_ENABLED : PANE_HEIGHT_DISABLED });
  }, [indicators.MACD.enabled]);
  useEffect(() => {
    const e = indicators.BOLLINGER.enabled;
    bbUpperRef.current?.applyOptions({ visible: e });
    bbMiddleRef.current?.applyOptions({ visible: e });
    bbLowerRef.current?.applyOptions({ visible: e });
    // Bollinger Bands live on pane 0 (price scale) — no pane collapse needed.
  }, [indicators.BOLLINGER.enabled]);
  useEffect(() => {
    const e = indicators.ATR.enabled;
    atrRef.current?.applyOptions({ visible: e });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chartRef.current?.panes?.()[3] as any)?.setOptions?.({ height: e ? PANE_HEIGHT_ENABLED : PANE_HEIGHT_DISABLED });
  }, [indicators.ATR.enabled]);
  useEffect(() => {
    const e = indicators.STOCHASTIC.enabled;
    stochKRef.current?.applyOptions({ visible: e });
    stochDRef.current?.applyOptions({ visible: e });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chartRef.current?.panes?.()[4] as any)?.setOptions?.({ height: e ? PANE_HEIGHT_ENABLED : PANE_HEIGHT_DISABLED });
  }, [indicators.STOCHASTIC.enabled]);
  useEffect(() => {
    const e = indicators.OBV.enabled;
    obvRef.current?.applyOptions({ visible: e });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (chartRef.current?.panes?.()[5] as any)?.setOptions?.({ height: e ? PANE_HEIGHT_ENABLED : PANE_HEIGHT_DISABLED });
  }, [indicators.OBV.enabled]);
  useEffect(() => { vwapRef.current?.applyOptions({ visible: indicators.VWAP.enabled }); }, [indicators.VWAP.enabled]);
  useEffect(() => { volMA20Ref.current?.applyOptions({ visible: showVolMA20 }); }, [showVolMA20]);
  useEffect(() => { vwapLineRef.current?.applyOptions({ visible: showVWAPLine }); }, [showVWAPLine]);

  // Log-scale (mode 0=Normal, 1=Logarithmic) and fullscreen resize
  useEffect(() => {
    chartRef.current?.priceScale("right").applyOptions({ mode: logScale ? 1 : 0 });
  }, [logScale]);
  useEffect(() => {
    if (!chartRef.current || !containerRef.current) return;
    chartRef.current.applyOptions(isFullscreen
      ? { width: window.innerWidth, height: window.innerHeight - 60 }
      : { width: containerRef.current.clientWidth, height: CHART_HEIGHT });
  }, [isFullscreen, containerRef]);

  return { chartRef, seriesRef, volumeSeriesRef, compareSeriesRef, converters, isChartReady, chartError };
}
