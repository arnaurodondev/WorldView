/**
 * components/instrument/chart/useChartSeries.ts — lightweight-charts series management hook
 * Manages: chart init, all indicator series refs, data-update effect, visibility effects.
 * Series creation is delegated to createChartSeries.ts (plain async factory).
 * PLAN REFERENCE: PLAN-0089 Wave D-1 | WHO USES IT: OHLCVChart.tsx
 *
 * ADDITIONS (chart-type toggle + range presets + oscillator dedup):
 *
 * chartType ("candle"|"line"|"area"):
 *   When the user switches chart type, the main series is removed from the chart
 *   and a new series of the requested type is created in its place. The series ref
 *   is updated so data-update effects work correctly on subsequent bar fetches.
 *   WHY remove+recreate (not applyOptions): lightweight-charts v5 has no
 *   changeSeries() API — a series is bound to its type at creation. Removing the
 *   old series and adding a new one is the canonical v5 approach. We re-populate
 *   the new series immediately with the last known bar data so there is no blank flash.
 *
 * setVisibleRange (range presets):
 *   Exposed via the return value so OHLCVChart can call it from its onRangePreset
 *   handler. The hook keeps the chart ref encapsulated; callers never touch chartRef
 *   directly — they call setVisibleRange(preset) and the hook translates to the
 *   appropriate lightweight-charts timeScale API call.
 *
 * Oscillator deduplication (Task 3):
 *   The IND-pane RSI and MACD are suppressed when the TAOverlayPanel chip strip
 *   produces overlays with ids "rsi-14" or "macd-line" (both chip-strip and IND
 *   pane would render the same indicator — duplicate). The visibility effect checks
 *   the incoming `overlays` array before applying the IND pane show/hide.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { createAllChartSeries } from "@/components/instrument/chart/createChartSeries";
import type { ChartType, RangePreset } from "@/lib/chart-adapter";

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
import type { OverlaySeries } from "@/components/instrument/chart/OHLCVChart";

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
  /**
   * PLAN-0091 F-1: optional TA overlay lines from TAOverlayPanel.
   * Each item becomes a dynamic lightweight-charts LineSeries keyed by `id`.
   * When the array changes, removed entries are deleted from the chart and new
   * entries are created. The chart is NOT re-initialised — series are mutated
   * in-place which avoids the scroll-to-1985 / screen-flash issues (BP-376/450).
   */
  overlays?: OverlaySeries[];
  /**
   * Active chart rendering type — controls the main price series kind.
   * Defaults to "candle" when omitted. When changed, the old main series is
   * removed and a new series of the requested type is created in its place.
   */
  chartType?: ChartType;
}

export interface UseChartSeriesReturn {
  chartRef: React.MutableRefObject<IChartApi | null>;
  seriesRef: React.MutableRefObject<ISeriesApi<"Candlestick"> | null>;
  volumeSeriesRef: React.MutableRefObject<ISeriesApi<"Histogram"> | null>;
  compareSeriesRef: React.MutableRefObject<ISeriesApi<"Line"> | null>;
  converters: CoordinateConverter | null;
  isChartReady: boolean;
  chartError: boolean;
  /**
   * setVisibleRange — applies a range preset to the chart's timeScale.
   *
   * WHY exposed (not handled inline): OHLCVChart owns this hook and also owns
   * the onRangePreset handler. Exposing setVisibleRange keeps the chart ref
   * encapsulated in the hook while letting OHLCVChart wire the toolbar callback.
   * Callers must not call this before the chart is initialised (chartRef is null
   * before the async import completes — the function no-ops in that case).
   */
  setVisibleRange: (preset: RangePreset) => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChartSeries({
  containerRef, isFullscreen, isFullscreenRef, indicators,
  showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
  data, instrumentId, timeframe, logScaleRef, logScale,
  onVolumeProfileBuckets, overlays, chartType = "candle",
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

  // ── Dynamic overlay series (PLAN-0091 F-1) ────────────────────────────────
  // WHY a Map (not an array of refs): TAOverlayPanel can add/remove individual
  // overlays by id (e.g. toggle "ema-20" off without touching "sma-200"). A Map
  // lets us diff the current vs. next overlay set in O(n) and call removeSeries()
  // only on the entries that disappeared, avoiding a full chart re-init.
  const overlaySeriesMap = useRef<Map<string, ISeriesApi<"Line">>>(new Map());

  // ── Chart type alternate series refs ──────────────────────────────────────
  // WHY separate refs per type (not a union ref): the series API types differ —
  // ISeriesApi<"Line"> vs ISeriesApi<"Area"> — so a single ref cannot be safely
  // typed without `any`. Separate nullable refs keep type safety explicit.
  // At most one of these is non-null at any time (the currently active type).
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const areaSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  // WHY chartTypeRef (not just chartType prop): the chart-type switch effect
  // needs to compare the PREVIOUS type with the incoming type to know which
  // series to remove. A ref always reflects the committed state without triggering
  // extra effect runs; it's updated at the end of the switch effect.
  const chartTypeRef = useRef<ChartType>("candle");

  // WHY lastBarsRef: the chart-type switch effect needs bar data to populate the
  // newly created series immediately (no blank flash). But bars live in the
  // data-update effect's closure. A ref provides a stable pointer to the last
  // seen bars array that the switch effect can read without a dependency cycle.
  const lastBarsRef = useRef<OHLCVBar[]>([]);

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
        const handles = await createAllChartSeries(
          chart, LineSeries, HistogramSeries, CandlestickSeries,
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
      // Clear the dynamic overlay map — series handles are now invalid after chart.remove()
      overlaySeriesMap.current.clear();
      // Reset alternate-type series refs — they're invalid after chart.remove()
      lineSeriesRef.current = null; areaSeriesRef.current = null;
      chartTypeRef.current = "candle";
      setConverters(null);
    };
  }, []); // empty deps: chart init runs once on mount, cleanup on unmount
  // eslint-disable-next-line react-hooks/exhaustive-deps

  // ── Update chart data when bars change ────────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current || !data?.bars) return;

    // Keep lastBarsRef current so the chart-type-switch effect can re-populate
    // a freshly created series with up-to-date data (no blank flash on type change).
    lastBarsRef.current = data.bars;

    const formattedBars: FormattedBar[] = data.bars.map((bar) => ({
      time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
      open: bar.open, high: bar.high, low: bar.low, close: bar.close,
      volume: bar.volume ?? 0,
    }));

    // ── Push data to the active chart type series ──────────────────────────
    // WHY three branches: only one of candle/line/area is active at a time.
    // The candlestick series is the default (always created by createAllChartSeries).
    // When type is "line" or "area", seriesRef still exists (never removed) but is
    // hidden — we push data to the active alternate series instead.
    if (chartTypeRef.current === "candle") {
      // Candlestick (default) — seriesRef IS the main price series.
      setSeriesData(seriesRef.current, formattedBars);
    } else {
      // Line / Area — seriesRef is hidden; push close values to the alternate series.
      const closePts = formattedBars.map((b) => ({ time: b.time, value: b.close }));
      if (chartTypeRef.current === "line") setSeriesData(lineSeriesRef.current, closePts);
      // WHY direct .setData() for area (not setSeriesData): setSeriesData is typed for
      // Line|Histogram|Candlestick; ISeriesApi<"Area"> is a distinct type in lw-charts v5.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (chartTypeRef.current === "area") areaSeriesRef.current?.setData(closePts as any);
    }
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
  useEffect(() => { volumeSeriesRef.current?.applyOptions({ visible: showVolume }); }, [showVolume]);
  useEffect(() => { ma50SeriesRef.current?.applyOptions({ visible: showMA50 }); }, [showMA50]);
  useEffect(() => { ma200SeriesRef.current?.applyOptions({ visible: showMA200 }); }, [showMA200]);

  // ── Oscillator deduplication (Task 3) ─────────────────────────────────────
  // WHY suppress IND-pane RSI when chip-strip RSI overlay is active:
  //   The TAOverlayPanel chip strip renders RSI as id="rsi-14" on the price scale.
  //   The IND dropdown renders RSI as a separate pane oscillator (rsiPaneRef).
  //   Having both active produces duplicate RSI data in two visual forms — confusing.
  //   Rule: chip-strip wins. If overlays contains "rsi-14", the IND pane is hidden
  //   regardless of the indicators.RSI.enabled flag.
  //
  // WHY also check "macd-line": TAOverlayPanel chips use id="macd-line" for the MACD
  //   line overlay on the price scale. The IND pane uses macdLineRef/Signal/Hist.
  //   Same dedup rule applies.
  const chipRSIActive = (overlays ?? []).some((o) => o.id === "rsi-14");
  const chipMACDActive = (overlays ?? []).some((o) => o.id === "macd-line");

  useEffect(() => {
    // RSI pane: visible only if IND flag is on AND chip-strip RSI is NOT active.
    rsiPaneRef.current?.applyOptions({ visible: indicators.RSI.enabled && !chipRSIActive });
  }, [indicators.RSI.enabled, chipRSIActive]);

  useEffect(() => {
    // MACD pane: same dedup rule as RSI.
    const e = indicators.MACD.enabled && !chipMACDActive;
    macdLineRef.current?.applyOptions({ visible: e });
    macdSignalRef.current?.applyOptions({ visible: e });
    macdHistRef.current?.applyOptions({ visible: e });
  }, [indicators.MACD.enabled, chipMACDActive]);
  useEffect(() => {
    const e = indicators.BOLLINGER.enabled;
    bbUpperRef.current?.applyOptions({ visible: e });
    bbMiddleRef.current?.applyOptions({ visible: e });
    bbLowerRef.current?.applyOptions({ visible: e });
  }, [indicators.BOLLINGER.enabled]);
  useEffect(() => { atrRef.current?.applyOptions({ visible: indicators.ATR.enabled }); }, [indicators.ATR.enabled]);
  useEffect(() => {
    const e = indicators.STOCHASTIC.enabled;
    stochKRef.current?.applyOptions({ visible: e });
    stochDRef.current?.applyOptions({ visible: e });
  }, [indicators.STOCHASTIC.enabled]);
  useEffect(() => { obvRef.current?.applyOptions({ visible: indicators.OBV.enabled }); }, [indicators.OBV.enabled]);
  useEffect(() => { vwapRef.current?.applyOptions({ visible: indicators.VWAP.enabled }); }, [indicators.VWAP.enabled]);
  useEffect(() => { volMA20Ref.current?.applyOptions({ visible: showVolMA20 }); }, [showVolMA20]);
  useEffect(() => { vwapLineRef.current?.applyOptions({ visible: showVWAPLine }); }, [showVWAPLine]);

  // ── PLAN-0091 F-1: Dynamic overlay series management ──────────────────────
  // WHY a separate effect (not inside the data-update effect): overlays can
  // change independently of bars (user toggles a chip while bars stay cached).
  // Keeping the two effects separate means each runs only when its own inputs
  // change — avoids the O(series * bars) double-computation on every bar update.
  //
  // Algorithm (diff-based, avoids chart re-init):
  //   1. Remove series whose id is no longer in the incoming overlays array.
  //   2. For series still present, update their data in-place.
  //   3. For new series, create a LineSeries and populate it.
  //
  // WHY LineSeries on priceScaleId "right": all TA overlays are price-scale
  // overlaid (EMA/SMA/VWAP); axis="right" is the candlestick scale. Using
  // "right" keeps the overlay price scale shared with the candles — no
  // independent Y-axis which would stretch the chart panes.
  useEffect(() => {
    // Guard: chart must be initialised and we need bars to map timestamps to
    // lightweight-charts `Time` values (required by setData).
    if (!chartRef.current || !data?.bars) return;

    // Dynamic import is needed because lightweight-charts v5 uses ESM-only
    // exports. We resolve the LineSeries constructor from the already-loaded
    // chart instance to avoid a second import round-trip.
    // WHY async IIFE instead of top-level await: useEffect callbacks must be
    // synchronous; async logic runs inside a fire-and-forget IIFE.
    void (async () => {
      // Bail if chart was torn down while we awaited the import.
      if (!chartRef.current || !data?.bars) return;

      const { LineSeries } = await import("lightweight-charts");
      if (!chartRef.current || !data?.bars) return;

      const chart = chartRef.current;
      const bars = data.bars;
      const incomingIds = new Set((overlays ?? []).map((o) => o.id));

      // Step 1: Remove series that are no longer in the overlays array.
      for (const [id, series] of overlaySeriesMap.current) {
        if (!incomingIds.has(id)) {
          try { chart.removeSeries(series); } catch { /* chart may have been torn down */ }
          overlaySeriesMap.current.delete(id);
        }
      }

      // Step 2 + 3: Update existing or create new series.
      for (const overlay of overlays ?? []) {
        let series = overlaySeriesMap.current.get(overlay.id);

        if (!series) {
          // New overlay — create a lightweight-charts LineSeries.
          series = chart.addSeries(LineSeries, {
            color: overlay.color,
            lineWidth: (overlay.strokeWidth ?? 1) as 1 | 2 | 3 | 4,
            priceScaleId: "right",
            // WHY lastValueVisible: false — the overlay label (e.g. "EMA 20 ▲132.40")
            // would clutter the right-axis price labels alongside the candlestick close.
            lastValueVisible: false,
            // WHY crosshairMarkerVisible: false — the crosshair already shows the
            // candlestick OHLCV tooltip; a second marker per overlay line is noisy.
            crosshairMarkerVisible: false,
          }) as ISeriesApi<"Line">;
          overlaySeriesMap.current.set(overlay.id, series);
        } else {
          // Existing overlay — update color/width in case the chip was re-configured.
          series.applyOptions({
            color: overlay.color,
            lineWidth: (overlay.strokeWidth ?? 1) as 1 | 2 | 3 | 4,
          });
        }

        // Map bar timestamps to lightweight-charts `Time` values and skip NaN
        // entries (insufficient history points during TA warm-up).
        const lineData = bars
          .map((bar, i) => ({
            time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
            value: overlay.data[i],
          }))
          .filter((pt) => !isNaN(pt.value));

        setSeriesData(series, lineData);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlays, data?.bars]);

  // ── Chart type switch effect ───────────────────────────────────────────────
  // WHY a separate effect (not inside chart init): chart type can change at any
  // time after init (user clicks C/L/A). The init effect runs only once on mount;
  // this effect runs when `chartType` changes.
  //
  // Approach:
  //   1. Hide or show the CandlestickSeries (seriesRef) depending on type.
  //   2. If type is "line" and lineSeriesRef is null → create LineSeries.
  //   3. If type is "area" and areaSeriesRef is null → create AreaSeries.
  //   4. Show only the active series; hide the others.
  //   5. Populate the new series with the last known bars so there is no blank flash.
  //   6. Update chartTypeRef so the data-update effect knows which series to push to.
  useEffect(() => {
    if (!chartRef.current) return;

    void (async () => {
      if (!chartRef.current) return;

      const { LineSeries, AreaSeries } = await import("lightweight-charts");
      if (!chartRef.current) return;

      const chart = chartRef.current;

      // Helper: map raw OHLCVBar array to close-price line data.
      const toClosePts = (bars: OHLCVBar[]) =>
        bars.map((bar) => ({
          time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
          value: bar.close,
        }));

      if (chartType === "candle") {
        // Restore the CandlestickSeries and hide alternates.
        seriesRef.current?.applyOptions({ visible: true });
        lineSeriesRef.current?.applyOptions({ visible: false });
        areaSeriesRef.current?.applyOptions({ visible: false });
      } else if (chartType === "line") {
        // Hide candlestick + area; show (or create) line series.
        seriesRef.current?.applyOptions({ visible: false });
        areaSeriesRef.current?.applyOptions({ visible: false });

        if (!lineSeriesRef.current) {
          // WHY same colour as MA50 (FFD60A): line chart uses yellow for trend
          // visibility on the dark terminal background. lastValueVisible/crosshair
          // follow the same rationale as overlay series — avoid cluttering the axis.
          lineSeriesRef.current = chart.addSeries(LineSeries, {
            color: "#FFD60A",
            lineWidth: 2,
            priceScaleId: "right",
            lastValueVisible: true,
            crosshairMarkerVisible: true,
          }) as ISeriesApi<"Line">;
          setSeriesData(lineSeriesRef.current, toClosePts(lastBarsRef.current));
        } else {
          lineSeriesRef.current.applyOptions({ visible: true });
        }
      } else if (chartType === "area") {
        // Hide candlestick + line; show (or create) area series.
        seriesRef.current?.applyOptions({ visible: false });
        lineSeriesRef.current?.applyOptions({ visible: false });

        if (!areaSeriesRef.current) {
          // WHY sky-blue fill (#0EA5E9): area charts work best with a contrasting
          // fill. Sky-blue is a distinct Midnight Pro accent not used by any other
          // series in pane 0, so there is no visual conflict.
          areaSeriesRef.current = chart.addSeries(AreaSeries, {
            topColor: "#0EA5E940",
            bottomColor: "#0EA5E910",
            lineColor: "#0EA5E9",
            lineWidth: 2,
            priceScaleId: "right",
            lastValueVisible: true,
            crosshairMarkerVisible: true,
          }) as ISeriesApi<"Area">;
          // WHY direct .setData() (not setSeriesData): see comment in data-update effect.
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          areaSeriesRef.current.setData(toClosePts(lastBarsRef.current) as any);
        } else {
          areaSeriesRef.current.applyOptions({ visible: true });
        }
      }

      chartTypeRef.current = chartType;
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartType]);

  // ── Range preset handler ──────────────────────────────────────────────────
  // WHY useCallback: this function is passed back to OHLCVChart which wires it to
  // the toolbar. Without useCallback it would be a new function on every render,
  // causing unnecessary re-renders of the toolbar.
  //
  // Preset → timeScale API mapping:
  //   YTD → setVisibleRange from Jan 1 of current year to today
  //   3Y  → setVisibleRange from today − 3 years to today
  //   5Y  → setVisibleRange from today − 5 years to today
  //   ALL → fitContent() (shows all loaded bars regardless of date range)
  //
  // WHY Unix seconds (not Date objects): lightweight-charts timeScale expects
  // UTCTimestamp = Unix seconds. We use Math.floor(ms / 1000) as with toTime().
  const setVisibleRange = useCallback((preset: RangePreset) => {
    const ts = chartRef.current?.timeScale();
    if (!ts) return;

    if (preset === "ALL") {
      ts.fitContent();
      return;
    }

    const nowMs = Date.now();
    const todaySecs = toTime(Math.floor(nowMs / 1000));
    let fromSecs: ReturnType<typeof toTime>;

    if (preset === "YTD") {
      const jan1 = new Date(new Date().getFullYear(), 0, 1).getTime();
      fromSecs = toTime(Math.floor(jan1 / 1000));
    } else if (preset === "3Y") {
      fromSecs = toTime(Math.floor((nowMs - 3 * 365.25 * 24 * 3600 * 1000) / 1000));
    } else {
      // "5Y"
      fromSecs = toTime(Math.floor((nowMs - 5 * 365.25 * 24 * 3600 * 1000) / 1000));
    }

    try {
      ts.setVisibleRange({ from: fromSecs, to: todaySecs });
    } catch {
      // setVisibleRange throws if the range exceeds the loaded data;
      // fall back to fitContent which at least shows what we have.
      ts.fitContent();
    }
  }, []);

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

  return { chartRef, seriesRef, volumeSeriesRef, compareSeriesRef, converters, isChartReady, chartError, setVisibleRange };
}
