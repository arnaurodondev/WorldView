/**
 * components/instrument/OHLCVChart.tsx — OHLCV candlestick chart
 *
 * WHY THIS EXISTS: Institutional traders assess price action visually before
 * reading fundamentals. A candlestick chart communicates open/high/low/close
 * (the complete daily narrative) in a single glyph, unlike a line chart.
 *
 * WHY lightweight-charts: TradingView's open-source chart library. Zero external
 * dependencies, WebGL-accelerated, built for financial OHLCV data. Bloomberg
 * users are familiar with this chart style.
 *
 * WHY useEffect for chart init: lightweight-charts requires a DOM element to
 * mount. It MUST be initialised in a useEffect (browser-only) — never SSR.
 * The ref holds the chart instance to avoid re-creating on every render.
 *
 * WHY timeframe tabs: Different traders use different horizons. Day traders
 * need 5M, swing traders need 1D/1W, fund managers need 1W/1M.
 * 1W = weekly bars (S3 Timeframe.ONE_WEEK = "1w"); 1M = monthly bars
 * (S3 Timeframe.ONE_MONTH = "1M" — uppercase M, case-sensitive in the enum).
 *
 * WHY volume histogram: Volume confirms price action. A price breakout on high
 * volume is more significant than on low volume. Bloomberg always shows volume
 * beneath the price chart. The histogram uses lightweight-charts' priceScaleId
 * "volume" with scaleMargins to allocate the bottom 20% of chart height.
 *
 * WHY MA50/MA200 client-side computed: Moving averages are derived from the same
 * OHLCV bars already fetched — no additional API call needed. Client-side
 * computation with a simple SMA algorithm is fast even for 500 bars. The 200-day
 * MA requires at least 200 bars; if the timeframe has fewer, the line is empty.
 *
 * WAVE C ADDITIONS (PLAN-0050 §T-C-3-01, T-C-3-02, T-C-3-03, T-C-3-04):
 *   - 7 technical indicators (RSI, MACD, BB, ATR, STOCH, OBV, VWAP) with
 *     client-side computation and lightweight-charts series registration.
 *   - Left-side DrawingPalette + sibling SVG DrawingCanvas for annotations.
 *   - Volume submenu: Vol MA20, Volume Profile SVG overlay, VWAP Line.
 *   - Indicator + annotation state persisted via lib/instrument-context.ts.
 *
 * WHY 280px chart height (was 360px): Volume uses scaleMargins to occupy the
 * bottom 20% of the chart area. At 280px total, the candlestick area has ~224px
 * and volume has ~56px — matching TradingView's default proportion.
 *
 * WHO USES IT: OverviewLayout (within the chart+sidebar upper section)
 * DATA SOURCE: S9 GET /v1/ohlcv/{instrumentId}?timeframe=1D
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail chart, PLAN-0050 §Wave C
 */

"use client";
// WHY "use client": uses useEffect (DOM manipulation for chart init),
// useRef (chart instance), useState (timeframe + toolbar controls).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { DrawingPalette } from "@/components/instrument/DrawingPalette";
import { DrawingCanvas } from "@/components/instrument/DrawingCanvas";
import { VolumeProfileOverlay } from "@/components/instrument/VolumeProfileOverlay";
import { CrosshairHUD } from "@/components/instrument/CrosshairHUD";
// WHY import IChartApi / ISeriesApi / UTCTimestamp: typed refs eliminate all the
// `any`-casts that previously silenced TypeScript on chart + series method calls.
// IChartApi = the chart instance returned by createChart().
// ISeriesApi<T> = a generic series handle; T discriminates Candlestick/Line/Histogram.
// UTCTimestamp = branded number type (number & { _brand: "UTCTimestamp" }) that
// lightweight-charts uses to enforce time values are in Unix seconds (not ms).
// PLAN-0059 H-1: lightweight-charts upgraded to v5. v5 collapses series-creation
// into a single `chart.addSeries(SeriesDefinition, options)` factory; no more
// `chart.addSeries(CandlestickSeries,opts)` / `chart.addSeries(LineSeries,opts)` shortcuts.
// Series-definition values (CandlestickSeries / LineSeries / HistogramSeries /
// AreaSeries) are imported from the package and passed as the first argument.
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { OHLCVBar } from "@/types/api";
import type { CoordinateConverter } from "@/components/instrument/DrawingCanvas";
import {
  loadIndicatorsFromStorage,
  saveIndicatorsToStorage,
  loadAnnotationsFromIDB,
  saveAnnotationsToIDB,
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
  type Annotation,
  type FormattedBar,
  type VolumeProfileBucket,
} from "@/lib/instrument-context";

// ── Types ─────────────────────────────────────────────────────────────────────

// WHY these exact values: they map directly to S3's Timeframe enum via the
// gateway normalizer in lib/gateway.ts. The gateway converts "5M"→"5m",
// "1H"→"1h", "1D"→"1d", "1W"→"1w", and preserves "1M" as-is (uppercase M)
// because S3's ONE_MONTH = "1M" is case-sensitive (lowercase "1m" is invalid).
type Timeframe = "5M" | "1H" | "1D" | "1W" | "1M";

interface OHLCVChartProps {
  instrumentId: string;
  /** Initial bars from CompanyOverview (last 30 days 1D — show immediately) */
  initialBars?: OHLCVBar[];
}

// ── Chart height constant ──────────────────────────────────────────────────────

// WHY 280 (was 360): volume histogram uses the bottom 20% (~56px), candlesticks
// use the top 80% (~224px). Total 280px matches TradingView's default proportion.
const CHART_HEIGHT = 280;

// WHY 28px palette width: w-7 Tailwind = 28px. The chart container gets pl-7 to
// offset the drawing palette. The SVG drawing canvas accounts for this offset.
const PALETTE_WIDTH = 28;

// ── Terminal Dark chart theme ──────────────────────────────────────────────────
// WHY inline object (not CSS): lightweight-charts applies these via its own theming
// API, not via CSS classes. Values must match the Terminal Dark palette exactly so
// the chart canvas blends seamlessly into the surrounding panel background.
//
// WHY these exact hex values (not CSS var() references):
// lightweight-charts does not understand CSS custom properties — it only accepts
// literal hex strings in its options object. The values below are derived from
// globals.css Terminal Dark tokens:
//   --background:        #09090B  (240 10% 4%)
//   --card:              #111113  (270 2% 7%)
//   --muted-foreground:  #71717A  (240 4% 46%)
//   --positive:          #26A69A  (174 42% 40%)
//   --negative:          #EF5350  (0 63% 62%)
//
// If the globals.css palette changes, update these constants to match.
const CHART_THEME = {
  layout: {
    background: { color: "#09090B" },   // --background: Terminal Dark near-black
    textColor: "#71717A",               // --muted-foreground: zinc-500 neutral grey
  },
  grid: {
    // WHY --card not --border for grid lines: #27272A (border) is too prominent
    // as a grid line — it competes with candlestick color. Using the card color
    // (#111113) gives a barely-visible grid that aids alignment without clutter.
    vertLines: { color: "#111113" },    // --card: subtle vertical grid
    horzLines: { color: "#111113" },    // --card: subtle horizontal grid
  },
  crosshair: {
    mode: 0, // Normal crosshair mode (shows both price and time crosshairs)
  },
};

// ── MA computation (simple SMA) ────────────────────────────────────────────────

/**
 * computeMA — simple moving average over an array of time/close pairs.
 *
 * WHY client-side: MAs are derived from the same bars already fetched — no
 * additional API call. Simple O(n*period) SMA is fast for ≤500 bars.
 *
 * WHY slice(period-1): the first valid MA point requires `period` bars of history.
 * Index 0 covers bars[0..period-1], so the time is bars[period-1].time.
 *
 * @param bars    Formatted bars with numeric time (Unix seconds) and close price
 * @param period  MA period (50 or 200)
 * @returns       Array of {time, value} pairs for lightweight-charts LineSeries
 */
function computeMA(
  bars: { time: number; close: number }[],
  period: number,
): { time: number; value: number }[] {
  if (bars.length < period) return [];
  return bars.slice(period - 1).map((_, i) => ({
    time: bars[i + period - 1].time,
    value: bars.slice(i, i + period).reduce((s, b) => s + b.close, 0) / period,
  }));
}

// ── UTCTimestamp helpers ───────────────────────────────────────────────────────

/**
 * toTime — cast a Unix-seconds number to lightweight-charts' branded UTCTimestamp.
 *
 * WHY needed: lightweight-charts uses a branded type `UTCTimestamp` (= number with
 * a `_brand: "UTCTimestamp"` phantom tag) so TypeScript can catch accidental
 * millisecond values being passed as seconds. Our computed timestamps are correct
 * Unix seconds — the cast is safe. Using `as UTCTimestamp` instead of `as any`
 * keeps the intent explicit and avoids widening to `any` in the call sites.
 */
function toTime(t: number): UTCTimestamp {
  return t as UTCTimestamp;
}

/**
 * setSeriesData — null-safe typed setData wrapper for lightweight-charts series.
 *
 * WHY needed: ISeriesApi<T>.setData() expects exactly the data shape for T.
 * Our computed indicator data arrays (e.g., { time: number; value: number }[])
 * are semantically correct, but TypeScript needs the `time` field as UTCTimestamp
 * and the shape to match the series discriminant. We use a `as unknown as P[0]`
 * double-cast which is safe given that the data is already correctly structured.
 *
 * WHY generic S (not `any`): keeps the series type trackable for IDE tooling.
 * The `Parameters<S["setData"]>[0]` trick extracts the exact argument type from
 * the series' setData overload without needing to know T explicitly.
 */
function setSeriesData<S extends ISeriesApi<"Line" | "Histogram" | "Candlestick">>(
  series: S | null,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any[],
): void {
  if (!series) return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  series.setData(data as any);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OHLCVChart({ instrumentId, initialBars }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  // ── Original toolbar toggle state ──────────────────────────────────────────
  // WHY default showVolume=true: volume is standard in all financial charting UIs.
  // MA50/MA200 default off — adding them is an intentional analyst decision.
  const [showVolume, setShowVolume] = useState(true);
  const [showMA50, setShowMA50] = useState(false);
  const [showMA200, setShowMA200] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // WHY isFullscreenRef: the ResizeObserver callback is captured inside a useEffect
  // with empty deps, so it holds a stale closure over `isFullscreen`. A ref stays
  // current across renders and can be read inside the stale closure safely.
  const isFullscreenRef = useRef(false);

  // ── Wave C: Indicator state (T-C-3-01, T-C-3-04) ─────────────────────────
  // WHY lazy init via function: loadIndicatorsFromStorage reads localStorage.
  // Using a lazy initialiser avoids calling it on every re-render.
  const [indicators, setIndicators] = useState<Record<IndicatorId, IndicatorConfig>>(
    () => loadIndicatorsFromStorage(),
  );

  // ── Wave C: Volume submenu state (T-C-3-03) ────────────────────────────────
  const [showVolMA20, setShowVolMA20] = useState(false);
  const [showVolProfile, setShowVolProfile] = useState(false);
  const [showVWAPLine, setShowVWAPLine] = useState(false);

  // ── PLAN-0059 H-2: log-scale toggle ───────────────────────────────────────
  // WHY default false: linear is the institutional default. Log mode helps
  // when comparing percentage changes across very different absolute prices
  // (e.g. AAPL at $180 vs BRK.A at $700k). One toolbar toggle.
  const [logScale, setLogScale] = useState(false);
  // logScaleRef captures the current toggle so the async chart-init effect
  // can apply the user's pre-init choice once the chart resolves. Without
  // this, toggling before the dynamic import resolves silently dropped.
  const logScaleRef = useRef(logScale);
  logScaleRef.current = logScale;

  // ── Wave C: Volume profile data (computed from bars, not lightweight-charts) ─
  const [volumeProfileBuckets, setVolumeProfileBuckets] = useState<VolumeProfileBucket[]>([]);

  // ── Wave C: Drawing palette + annotation state (T-C-3-02, T-C-3-04) ────────
  const [activeTool, setActiveTool] = useState<import("@/lib/instrument-context").DrawingToolId | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);

  // ── Coordinate converters for DrawingCanvas ────────────────────────────────
  // WHY null initial: chart hasn't init'd yet. DrawingCanvas checks for null.
  const [converters, setConverters] = useState<CoordinateConverter | null>(null);

  // WHY chartError state: if the dynamic import for lightweight-charts fails (e.g.,
  // CDN down, bundle corruption, network timeout), we show a fallback instead of
  // blank space. Financial UI must NEVER silently fail — blank charts erode trust.
  const [chartError, setChartError] = useState(false);

  // WHY sync effect: keeps isFullscreenRef.current in step with the state value so
  // the ResizeObserver closure (which is stale by design) can read the current value.
  useEffect(() => {
    isFullscreenRef.current = isFullscreen;
  }, [isFullscreen]);

  const containerRef = useRef<HTMLDivElement>(null);

  // WHY useRef for chart + series: preserves instances across re-renders without
  // causing re-renders themselves (unlike useState which would create a loop).
  // WHY IChartApi / ISeriesApi<T>: proper types from lightweight-charts replace
  // the former `any` casts. ISeriesApi<"Candlestick"> and ISeriesApi<"Line"> are
  // the correct discriminants for the respective series types created below.
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);       // candlestick series
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);   // volume histogram series
  const ma50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);          // MA50 line series
  const ma200SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);         // MA200 line series

  // ── Wave C: Indicator series refs ──────────────────────────────────────────
  // WHY refs (not state): series objects are mutable lightweight-charts handles.
  // We call .setData() and .applyOptions() directly. Storing them in state would
  // cause an infinite loop (setState → re-render → series-update effect → setState).
  const rsiPaneRef = useRef<ISeriesApi<"Line"> | null>(null);             // RSI line series (sub-pane)
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);            // MACD line
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);          // MACD signal line
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);       // MACD histogram
  const bbUpperRef = useRef<ISeriesApi<"Line"> | null>(null);             // Bollinger upper band
  const bbMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);            // Bollinger middle (SMA)
  const bbLowerRef = useRef<ISeriesApi<"Line"> | null>(null);             // Bollinger lower band
  const atrRef = useRef<ISeriesApi<"Line"> | null>(null);                 // ATR line (sub-pane)
  const stochKRef = useRef<ISeriesApi<"Line"> | null>(null);              // Stochastic %K
  const stochDRef = useRef<ISeriesApi<"Line"> | null>(null);              // Stochastic %D
  const obvRef = useRef<ISeriesApi<"Line"> | null>(null);                 // OBV line (main price pane)
  const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);                // VWAP line (main price pane)
  const volMA20Ref = useRef<ISeriesApi<"Line"> | null>(null);             // Volume MA20 (volume pane)
  const vwapLineRef = useRef<ISeriesApi<"Line"> | null>(null);            // VWAP anchored (main pane, vol submenu)

  // PLAN-0053 T-A-1-01: stabilise placeholderData reference. A fresh object
  // literal on every render makes React Query return a new `data` reference,
  // which re-fires the data-update effect (line ~711, dep `data?.bars`),
  // which calls setVolumeProfileBuckets, which re-renders → infinite loop
  // (manifests as the chart auto-scrolling into the past). useMemo keeps the
  // placeholder reference stable across renders so the effect only fires when
  // the actual bars array changes.
  const memoizedPlaceholder = useMemo(() => {
    if (initialBars && timeframe === "1D") {
      return {
        instrument_id: instrumentId,
        ticker: "",
        timeframe: "1D" as const,
        bars: initialBars,
      };
    }
    return undefined;
  }, [initialBars, timeframe, instrumentId]);

  const { data, isLoading } = useQuery({
    queryKey: ["ohlcv", instrumentId, timeframe],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId, { timeframe }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 60_000, // WHY 1min: OHLCV bars don't change within the same candle period
    placeholderData: memoizedPlaceholder,
  });

  // ── Load annotations from IndexedDB on mount / instrumentId change ─────────
  // WHY separate effect (not combined with chart init): chart init is a one-time
  // operation that runs once and holds state in refs. Annotation loading is
  // per-instrument — it must re-run when the user navigates to a different instrument.
  // Combining them would require clearing and re-creating chart series on instrument
  // change, which is complex. Separate effects are simpler.
  useEffect(() => {
    let cancelled = false;
    loadAnnotationsFromIDB(instrumentId).then((savedAnnotations) => {
      if (!cancelled) setAnnotations(savedAnnotations);
    });
    return () => { cancelled = true; };
  }, [instrumentId]);

  // ── Chart init & cleanup ───────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    // WHY dynamic import: lightweight-charts uses browser APIs unavailable at SSR.
    // Dynamic import ensures it only loads client-side.
    let chart: IChartApi | null = null;

    async function initChart() {
      try {
        // v5 factory imports — see header note. SeriesDefinition values are
        // passed to chart.addSeries(...) as the first arg.
        const {
          createChart,
          CandlestickSeries,
          LineSeries,
          HistogramSeries,
        } = await import("lightweight-charts");

        // WHY null check after await: dynamic import is async — by the time it
        // resolves, the component may have unmounted and the ref may be null.
        if (!containerRef.current) return;

        chart = createChart(containerRef.current, {
          width: containerRef.current.clientWidth,
          height: CHART_HEIGHT,
          layout: CHART_THEME.layout,
          grid: CHART_THEME.grid,
          crosshair: CHART_THEME.crosshair,
          rightPriceScale: {
            // WHY #111113 (--card): recessive structural edge — data, not frame,
            // should draw the eye.
            borderColor: "#111113",
          },
          timeScale: {
            borderColor: "#111113",
            timeVisible: true,
          },
        });

        // ── Candlestick series ─────────────────────────────────────────────
        const series = chart.addSeries(CandlestickSeries,{
          upColor: "#26A69A",         // --positive: teal-green (bullish)
          downColor: "#EF5350",       // --negative: muted red (bearish)
          borderUpColor: "#26A69A",
          borderDownColor: "#EF5350",
          wickUpColor: "#26A69A",
          wickDownColor: "#EF5350",
        });

        chartRef.current = chart;
        seriesRef.current = series;

        // QA iter-1 fix: apply the user's log-scale preference NOW. If the
        // user toggled `log` before the chart resolved, the dependent effect
        // ran with a null chart ref and was a no-op. Reading via ref keeps it
        // current at init time.
        chart.priceScale("right").applyOptions({ mode: logScaleRef.current ? 1 : 0 });

        // ── Volume histogram series ────────────────────────────────────────
        // WHY priceScaleId "volume": separates volume from the price scale,
        // preventing volume bars from affecting the candlestick Y range.
        // WHY scaleMargins top:0.8: volume occupies the bottom 20% of chart
        // height (~56px at CHART_HEIGHT=280) — the candlestick area uses 80%.
        const volumeSeries = chart.addSeries(HistogramSeries,{
          color: "#26A69A",           // default color; overridden per-bar
          priceFormat: { type: "volume" },
          priceScaleId: "volume",
        });
        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        volumeSeriesRef.current = volumeSeries;

        // ── MA50 line series (yellow, default hidden) ──────────────────────
        // WHY #FFD60A (primary yellow): primary yellow is the brand accent;
        // using it for MA50 ties the overlay to the platform's identity.
        const ma50Series = chart.addSeries(LineSeries,{
          color: "#FFD60A",
          lineWidth: 1,
          priceScaleId: "right",      // same scale as candlesticks
          visible: false,             // off by default — analyst opt-in
        });
        ma50SeriesRef.current = ma50Series;

        // ── MA200 line series (sky-500, default hidden) ────────────────────
        // WHY #0EA5E9 (sky-500): distinct from MA50 yellow; blue is a common
        // convention for MA200 in Bloomberg and TradingView.
        const ma200Series = chart.addSeries(LineSeries,{
          color: "#0EA5E9",
          lineWidth: 1,
          priceScaleId: "right",
          visible: false,             // off by default — analyst opt-in
        });
        ma200SeriesRef.current = ma200Series;

        // ── Wave C: Indicator series (all hidden by default) ───────────────

        // RSI — orange line in a dedicated sub-pane (0-100 scale separate from price)
        // WHY priceScaleId "rsi": creates a separate price scale for the RSI oscillator
        // so it doesn't affect the candlestick Y axis range.
        const rsiSeries = chart.addSeries(LineSeries,{
          color: "#F59E0B",           // amber — oscillator convention
          lineWidth: 1,
          priceScaleId: "rsi",
          visible: false,
        });
        chart.priceScale("rsi").applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
          // WHY autoScale:false: RSI is always 0-100. AutoScale would shrink the
          // range to the actual RSI values (e.g., 30-70) and lose the overbought/
          // oversold context. We let the scale clamp naturally via the data range.
          autoScale: true,
        });
        rsiPaneRef.current = rsiSeries;

        // MACD — three series: MACD line (purple), signal line (orange), histogram (teal/red)
        // WHY priceScaleId "macd": separate sub-pane below price and RSI
        const macdLine = chart.addSeries(LineSeries,{
          color: "#A78BFA",           // purple-400 — MACD line (TradingView convention)
          lineWidth: 1,
          priceScaleId: "macd",
          visible: false,
        });
        const macdSignal = chart.addSeries(LineSeries,{
          color: "#F59E0B",           // amber — signal line
          lineWidth: 1,
          priceScaleId: "macd",
          visible: false,
        });
        const macdHist = chart.addSeries(HistogramSeries,{
          color: "#26A69A",           // teal/red per bar in data
          priceScaleId: "macd",
          visible: false,
        });
        chart.priceScale("macd").applyOptions({
          scaleMargins: { top: 0.75, bottom: 0.05 },
        });
        macdLineRef.current = macdLine;
        macdSignalRef.current = macdSignal;
        macdHistRef.current = macdHist;

        // Bollinger Bands — three lines on the main price scale
        // WHY priceScaleId "right": BB overlays the candlesticks (same scale)
        // WHY dashed style: distinguishes BB from the solid MA50/MA200 lines
        const bbUpper = chart.addSeries(LineSeries,{
          color: "#6366F1",           // indigo-500
          lineWidth: 1,
          lineStyle: 2,               // dashed (lightweight-charts LineStyle.Dashed = 2)
          priceScaleId: "right",
          visible: false,
        });
        const bbMiddle = chart.addSeries(LineSeries,{
          color: "#6366F199",         // indigo-500 at 60% opacity (middle band = SMA)
          lineWidth: 1,
          priceScaleId: "right",
          visible: false,
        });
        const bbLower = chart.addSeries(LineSeries,{
          color: "#6366F1",
          lineWidth: 1,
          lineStyle: 2,
          priceScaleId: "right",
          visible: false,
        });
        bbUpperRef.current = bbUpper;
        bbMiddleRef.current = bbMiddle;
        bbLowerRef.current = bbLower;

        // ATR — green line in a sub-pane (absolute $ volatility measure)
        const atrSeries = chart.addSeries(LineSeries,{
          color: "#10B981",           // emerald-500 — volatility = green convention
          lineWidth: 1,
          priceScaleId: "atr",
          visible: false,
        });
        chart.priceScale("atr").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        atrRef.current = atrSeries;

        // Stochastic — %K (teal) and %D (red) in a sub-pane
        const stochK = chart.addSeries(LineSeries,{
          color: "#26A69A",           // teal — %K fast line
          lineWidth: 1,
          priceScaleId: "stoch",
          visible: false,
        });
        const stochD = chart.addSeries(LineSeries,{
          color: "#EF5350",           // red — %D slow signal line
          lineWidth: 1,
          priceScaleId: "stoch",
          visible: false,
        });
        chart.priceScale("stoch").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        stochKRef.current = stochK;
        stochDRef.current = stochD;

        // OBV — sky-blue line on a separate OBV scale (cumulative volume units)
        const obvSeries = chart.addSeries(LineSeries,{
          color: "#38BDF8",           // sky-400 — OBV (volume-based, not price)
          lineWidth: 1,
          priceScaleId: "obv",
          visible: false,
        });
        chart.priceScale("obv").applyOptions({
          scaleMargins: { top: 0.75, bottom: 0.05 },
        });
        obvRef.current = obvSeries;

        // VWAP — pink line overlaid on the main price scale
        // WHY pink (#EC4899): VWAP is a price-level overlay (on the main scale)
        // but it's NOT a moving average (no smoothing). Pink distinguishes it
        // from MA50 (yellow) and MA200 (blue). TradingView uses pink for VWAP.
        const vwapSeries = chart.addSeries(LineSeries,{
          color: "#EC4899",
          lineWidth: 1,
          lineStyle: 1,               // dotted (VWAP convention — not a trend line)
          priceScaleId: "right",
          visible: false,
        });
        vwapRef.current = vwapSeries;

        // Volume MA20 — yellow-green line overlaid on the volume scale
        const volMA20Series = chart.addSeries(LineSeries,{
          color: "#84CC16",           // lime-500 — distinguishable on dark background
          lineWidth: 1,
          priceScaleId: "volume",
          visible: false,
        });
        volMA20Ref.current = volMA20Series;

        // VWAP Line (volume submenu variant) — same VWAP data, pink, anchored-daily label
        // WHY duplicate: the Indicators dropdown "VWAP" is for advanced users who know
        // the abbreviation. The Volume submenu "VWAP Line" is labeled more descriptively
        // for users browsing volume sub-indicators. Both drive the same data computation.
        const vwapLineSeries = chart.addSeries(LineSeries,{
          color: "#EC4899",
          lineWidth: 1,
          lineStyle: 1,
          priceScaleId: "right",
          visible: false,
        });
        vwapLineRef.current = vwapLineSeries;

        // ── Expose coordinate converters for DrawingCanvas ─────────────────
        // WHY after all series init: series ref (seriesRef.current) must be set
        // before we expose converters so DrawingCanvas can call priceToCoordinate.
        setConverters({ chart, series });

      } catch (err) {
        // WHY error boundary: if lightweight-charts CDN fails or the module is
        // missing (broken build, network issue), show a fallback UI instead of a
        // blank space. Financial UIs must never silently fail — a blank chart
        // looks like a price freeze and erodes trust.
        console.error("Failed to load chart library:", err);
        setChartError(true);
      }
    }

    initChart();

    // WHY ResizeObserver: chart must resize when container width changes
    const observer = new ResizeObserver(() => {
      // WHY isFullscreenRef.current (not isFullscreen): the closure is stale by
      // design (empty deps). The ref always reflects the current state value.
      if (chartRef.current && containerRef.current && !isFullscreenRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart?.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeSeriesRef.current = null;
      ma50SeriesRef.current = null;
      ma200SeriesRef.current = null;
      // Wave C series
      rsiPaneRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
      macdHistRef.current = null;
      bbUpperRef.current = null;
      bbMiddleRef.current = null;
      bbLowerRef.current = null;
      atrRef.current = null;
      stochKRef.current = null;
      stochDRef.current = null;
      obvRef.current = null;
      vwapRef.current = null;
      volMA20Ref.current = null;
      vwapLineRef.current = null;
      setConverters(null);
    };
  }, []); // WHY empty deps: chart init runs once on mount, cleanup on unmount

  // ── Update chart data when bars change ────────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current || !data?.bars) return;

    // Convert ISO timestamps to Unix time (lightweight-charts expects seconds)
    // WHY toTime(): lightweight-charts uses UTCTimestamp (branded number) for time fields.
    // Math.floor(getTime()/1000) produces the correct Unix seconds value; toTime() casts
    // it to the branded type without losing type safety elsewhere.
    const formattedBars: FormattedBar[] = data.bars.map((bar) => ({
      time: toTime(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume ?? 0,
    }));

    // WHY setData (not updateData): timeframe switch replaces the full dataset
    // WHY setSeriesData() wrapper: ISeriesApi<"Candlestick">.setData() expects
    // CandlestickData[] which uses UTCTimestamp. The helper handles the cast safely.
    setSeriesData(seriesRef.current, formattedBars);

    // ── Volume data ────────────────────────────────────────────────────────
    // WHY per-bar color: up-close bars → transparent green, down-close → transparent red.
    // WHY 40 alpha hex (25%): full opacity volume bars overpower the candlesticks.
    // Semi-transparent bars keep volume visually secondary to price action.
    setSeriesData(
      volumeSeriesRef.current,
      formattedBars.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "#26A69A40" : "#EF535040",
      })),
    );

    // ── MA50 / MA200 data ──────────────────────────────────────────────────
    setSeriesData(ma50SeriesRef.current, computeMA(formattedBars, 50));
    setSeriesData(ma200SeriesRef.current, computeMA(formattedBars, 200));

    // ── Wave C: Indicator data computations ────────────────────────────────
    // WHY compute all indicators (not just enabled ones): when a user enables an
    // indicator, it needs data immediately without waiting for the next bar fetch.
    // Computing all upfront is fast (all O(n) for n≤500 bars) and avoids the
    // "no data flash" when an indicator is first enabled after bars are loaded.

    // RSI
    setSeriesData(rsiPaneRef.current, computeRSI(formattedBars, 14));

    // MACD
    if (macdLineRef.current || macdSignalRef.current || macdHistRef.current) {
      const macdData = computeMACD(formattedBars, 12, 26, 9);
      setSeriesData(macdLineRef.current, macdData.map((d) => ({ time: d.time, value: d.macd })));
      setSeriesData(macdSignalRef.current, macdData.map((d) => ({ time: d.time, value: d.signal })));
      // WHY color per bar for histogram: positive histogram (MACD > signal) → teal;
      // negative (MACD < signal) → red. This is the standard MACD histogram coloring
      // used by TradingView and Bloomberg — instantly shows momentum direction.
      setSeriesData(
        macdHistRef.current,
        macdData.map((d) => ({
          time: d.time,
          value: d.histogram,
          color: d.histogram >= 0 ? "#26A69A80" : "#EF535080",
        })),
      );
    }

    // Bollinger Bands
    if (bbUpperRef.current || bbMiddleRef.current || bbLowerRef.current) {
      const bbData = computeBollinger(formattedBars, 20, 2);
      setSeriesData(bbUpperRef.current, bbData.map((d) => ({ time: d.time, value: d.upper })));
      setSeriesData(bbMiddleRef.current, bbData.map((d) => ({ time: d.time, value: d.middle })));
      setSeriesData(bbLowerRef.current, bbData.map((d) => ({ time: d.time, value: d.lower })));
    }

    // ATR
    setSeriesData(atrRef.current, computeATR(formattedBars, 14));

    // Stochastic
    if (stochKRef.current || stochDRef.current) {
      const stochData = computeStochastic(formattedBars, 14, 3, 3);
      setSeriesData(stochKRef.current, stochData.map((d) => ({ time: d.time, value: d.k })));
      setSeriesData(stochDRef.current, stochData.map((d) => ({ time: d.time, value: d.d })));
    }

    // OBV
    setSeriesData(obvRef.current, computeOBV(formattedBars));

    // VWAP (shared between Indicators dropdown and Volume submenu VWAP Line)
    const vwapData = computeVWAP(formattedBars);
    setSeriesData(vwapRef.current, vwapData);
    setSeriesData(vwapLineRef.current, vwapData);

    // Volume MA20
    setSeriesData(volMA20Ref.current, computeVolumeMA(formattedBars, 20));

    // Volume Profile (SVG overlay — not a lightweight-charts series)
    // WHY set in state: VolumeProfileOverlay is a React component that needs
    // re-render when profile data changes. Refs would prevent the re-render.
    setVolumeProfileBuckets(computeVolumeProfile(formattedBars, 24));

    if (formattedBars.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [data?.bars]);

  // ── Volume visibility toggle ───────────────────────────────────────────────
  useEffect(() => {
    volumeSeriesRef.current?.applyOptions({ visible: showVolume });
  }, [showVolume]);

  // ── MA50 visibility toggle ─────────────────────────────────────────────────
  useEffect(() => {
    ma50SeriesRef.current?.applyOptions({ visible: showMA50 });
  }, [showMA50]);

  // ── MA200 visibility toggle ────────────────────────────────────────────────
  useEffect(() => {
    ma200SeriesRef.current?.applyOptions({ visible: showMA200 });
  }, [showMA200]);

  // ── Wave C: Indicator visibility effects ──────────────────────────────────
  // WHY separate effect per indicator (not one combined): each indicator has a
  // different number of series to show/hide (RSI=1, MACD=3, BB=3, STOCH=2, etc.).
  // A single combined effect would need complex switch logic. Separate effects
  // are smaller and clearer — each one only cares about its indicator's series.

  useEffect(() => {
    const enabled = indicators.RSI.enabled;
    rsiPaneRef.current?.applyOptions({ visible: enabled });
  }, [indicators.RSI.enabled]);

  useEffect(() => {
    const enabled = indicators.MACD.enabled;
    macdLineRef.current?.applyOptions({ visible: enabled });
    macdSignalRef.current?.applyOptions({ visible: enabled });
    macdHistRef.current?.applyOptions({ visible: enabled });
  }, [indicators.MACD.enabled]);

  useEffect(() => {
    const enabled = indicators.BOLLINGER.enabled;
    bbUpperRef.current?.applyOptions({ visible: enabled });
    bbMiddleRef.current?.applyOptions({ visible: enabled });
    bbLowerRef.current?.applyOptions({ visible: enabled });
  }, [indicators.BOLLINGER.enabled]);

  useEffect(() => {
    atrRef.current?.applyOptions({ visible: indicators.ATR.enabled });
  }, [indicators.ATR.enabled]);

  useEffect(() => {
    const enabled = indicators.STOCHASTIC.enabled;
    stochKRef.current?.applyOptions({ visible: enabled });
    stochDRef.current?.applyOptions({ visible: enabled });
  }, [indicators.STOCHASTIC.enabled]);

  useEffect(() => {
    obvRef.current?.applyOptions({ visible: indicators.OBV.enabled });
  }, [indicators.OBV.enabled]);

  useEffect(() => {
    vwapRef.current?.applyOptions({ visible: indicators.VWAP.enabled });
  }, [indicators.VWAP.enabled]);

  // ── Wave C: Volume submenu visibility effects ──────────────────────────────
  useEffect(() => {
    volMA20Ref.current?.applyOptions({ visible: showVolMA20 });
  }, [showVolMA20]);

  useEffect(() => {
    vwapLineRef.current?.applyOptions({ visible: showVWAPLine });
  }, [showVWAPLine]);

  // ── PLAN-0059 H-2: apply log-scale to right price scale ───────────────────
  // mode 0 = Normal, 1 = Logarithmic, 2 = Percentage, 3 = IndexedTo100.
  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.priceScale("right").applyOptions({
      mode: logScale ? 1 : 0,
    });
  }, [logScale]);

  // ── Indicator toggle callback ──────────────────────────────────────────────
  // WHY useCallback: this is passed to ChartToolbar. Without useCallback, a new
  // function reference is created on every render, causing ChartToolbar to
  // re-render even when unrelated state changes.
  const handleToggleIndicator = useCallback((id: IndicatorId) => {
    setIndicators((prev) => {
      const updated = {
        ...prev,
        [id]: { ...prev[id], enabled: !prev[id].enabled },
      };
      // Persist to localStorage on every toggle
      saveIndicatorsToStorage(updated);
      return updated;
    });
  }, []);

  // ── Annotation handlers ────────────────────────────────────────────────────

  const handleAnnotationAdd = useCallback((annotation: Annotation) => {
    setAnnotations((prev) => {
      const next = [...prev, annotation];
      // Fire-and-forget IndexedDB persist
      void saveAnnotationsToIDB(instrumentId, next);
      return next;
    });
  }, [instrumentId]);

  const handleAnnotationDelete = useCallback((id: string) => {
    setAnnotations((prev) => {
      const next = prev.filter((a) => a.id !== id);
      void saveAnnotationsToIDB(instrumentId, next);
      return next;
    });
  }, [instrumentId]);

  // ── Escape key handler for fullscreen ───────────────────────────────────────
  // WHY separate useEffect: listens for Escape key only when fullscreen is active,
  // so we don't add unnecessary global key listeners during normal chart usage.
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsFullscreen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  // ── Fullscreen resize ──────────────────────────────────────────────────────
  // WHY separate effect (not inline toggle handler): the chart resize must happen
  // AFTER React commits the DOM change (the fixed overlay needs to be in the DOM
  // before we can measure its dimensions). useEffect runs after commit.
  useEffect(() => {
    if (!chartRef.current || !containerRef.current) return;
    if (isFullscreen) {
      // WHY window.innerHeight - 60: subtract ~60px for the toolbar row (h-7 = 28px)
      // plus a safety margin to prevent the chart from extending behind the toolbar.
      chartRef.current.applyOptions({
        width: window.innerWidth,
        height: window.innerHeight - 60,
      });
    } else {
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: CHART_HEIGHT,
      });
    }
  }, [isFullscreen]);

  return (
    // WHY conditional fixed positioning: fullscreen stretches chart to fill the
    // entire viewport (z-50 above all panels). Exit via ChartToolbar or Escape.
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-background flex flex-col" : ""}>

      {/* ── Combined toolbar: timeframe buttons + chart controls ─────────── */}
      {/* WHY single h-7 row (was mb-2 separate div): combines timeframe selector
          and overlay controls into one Bloomberg-style toolbar strip at terminal
          density. Saves vertical space vs the old 28px + margin layout. */}
      <div className="flex items-center h-7 px-2 border-b border-border/30 shrink-0">

        {/* Timeframe tabs — left side of toolbar */}
        {/* WHY this exact order: intraday (5M, 1H) → daily → weekly → monthly.
            1W/1M are added because S3 ingests weekly/monthly EODHD bars as
            first-class timeframes. */}
        {(["5M", "1H", "1D", "1W", "1M"] as Timeframe[]).map((tf) => (
          <button
            key={tf}
            onClick={() => setTimeframe(tf)}
            className={`rounded-[2px] px-2 py-0.5 text-[11px] font-medium transition-colors ${
              timeframe === tf
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tf}
          </button>
        ))}

        {/* QA iter-1: 1px hairline separator marks the visual class break
            between timeframe selection (high-frequency) and view-mode
            toggles (low-frequency, e.g. log). */}
        <span className="mx-1.5 h-3 w-px shrink-0 bg-border/50" aria-hidden />

        {/* PLAN-0059 H-2: log-scale toggle. Demoted from primary-tinted (which
            visually competed with active timeframe) to ghost+ring style: log
            is a rare-toggle view mode, not a timeframe sibling. */}
        <button
          onClick={() => setLogScale((v) => !v)}
          className={`rounded-[2px] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${
            logScale
              ? "text-foreground ring-1 ring-border bg-transparent"
              : "text-muted-foreground/70 hover:text-foreground"
          }`}
          aria-pressed={logScale}
          aria-label="Toggle logarithmic price scale"
          title="Logarithmic price scale"
        >
          log
        </button>

        {/* Chart overlay controls — right side of toolbar.
            QA iter-1: wrapping div with ml-auto anchors the cluster right
            and lets the left timeframe group shrink predictably at narrow
            panel widths. */}
        <div className="ml-auto flex items-center">
        <ChartToolbar
          showVolume={showVolume}
          onToggleVolume={() => setShowVolume((v) => !v)}
          showMA50={showMA50}
          onToggleMA50={() => setShowMA50((v) => !v)}
          showMA200={showMA200}
          onToggleMA200={() => setShowMA200((v) => !v)}
          isFullscreen={isFullscreen}
          onFullscreen={() => setIsFullscreen((v) => !v)}
          indicators={indicators}
          onToggleIndicator={handleToggleIndicator}
          showVolMA20={showVolMA20}
          onToggleVolMA20={() => setShowVolMA20((v) => !v)}
          showVolProfile={showVolProfile}
          onToggleVolProfile={() => setShowVolProfile((v) => !v)}
          showVWAPLine={showVWAPLine}
          onToggleVWAPLine={() => setShowVWAPLine((v) => !v)}
        />
        </div>
      </div>

      {/* ── Chart error fallback ────────────────────────────────────────── */}
      {chartError && (
        <div
          className="flex items-center justify-center rounded-[2px] border border-border bg-card"
          style={{ height: CHART_HEIGHT }}
        >
          <p className="text-sm text-muted-foreground">Chart unavailable</p>
        </div>
      )}

      {/* ── Chart wrapper with drawing palette + annotation overlay ─────────
          Layout (left to right):
            [28px DrawingPalette] [chart canvas + DrawingCanvas SVG] [right edge]

          The wrapper uses position:relative so the absolutely-positioned
          palette, SVG drawing canvas, and volume profile overlay can be
          positioned relative to the chart container boundary.

          WHY the chart container gets padding-left (pl-7): lightweight-charts
          renders into containerRef. If the palette sits above the containerRef
          div (not inside it), the chart would render under the palette. By
          applying pl-7 to the containerRef, the chart starts 28px from the left
          edge — exactly where the palette ends. The ResizeObserver reads
          containerRef.clientWidth which already excludes the padding.

          WHY keep chart container always in DOM (not conditional): the chart's
          WebGL context must persist. Removing and re-mounting containerRef would
          destroy and recreate the context — expensive and causes a flash.

          NOTE: The Skeleton and "refreshing" pill overlay the entire wrapper
          (including the palette area) for simplicity. At 280px total, the
          overlap is negligible. */}
      {!chartError && (
        <div className="relative w-full" data-testid="chart-wrapper">

          {/* ── Left-side drawing palette ─────────────────────────────────── */}
          {/* WHY inset-y-0: palette spans the full chart height (280px), not
              just the canvas area. The toolbar above and the stats strip below
              are outside the chart wrapper, so the palette won't overlap them. */}
          <DrawingPalette
            activeTool={activeTool}
            onSelectTool={setActiveTool}
            // WHY annotations.length: the palette shows a count badge at the bottom
            // so analysts can confirm their drawings are persisted even after closing/
            // reopening the tab. Passing the count (not the full array) avoids
            // re-rendering the palette on every annotation render pass.
            annotationCount={annotations.length}
          />

          {/* ── Chart canvas container ────────────────────────────────────── */}
          {/* WHY pl-7: offset chart canvas past the 28px drawing palette */}
          <div
            ref={containerRef}
            className={`w-full pl-7 ${isFullscreen ? "flex-1" : ""}`}
          />

          {/* ── SVG drawing annotation overlay ────────────────────────────── */}
          {/* WHY rendered over the chart container (not the palette): the DrawingCanvas
              covers only the chart canvas area (left offset by paletteWidth). Drawing
              on the palette area would intercept palette button clicks. */}
          <DrawingCanvas
            activeTool={activeTool}
            annotations={annotations}
            onAnnotationAdd={handleAnnotationAdd}
            onAnnotationDelete={handleAnnotationDelete}
            converters={converters}
            chartHeight={isFullscreen ? window.innerHeight - 60 : CHART_HEIGHT}
            paletteWidth={PALETTE_WIDTH}
          />

          {/* ── Volume Profile right-side SVG overlay ─────────────────────── */}
          {/* WHY conditional on showVolProfile: the buckets array may be populated
              but we should only render the overlay when the user has enabled it.
              Rendering with an empty array is safe but wastes a DOM node. */}
          {showVolProfile && (
            <VolumeProfileOverlay
              buckets={volumeProfileBuckets}
              converters={converters}
              chartHeight={isFullscreen ? window.innerHeight - 60 : CHART_HEIGHT}
              profileWidth={60}
            />
          )}

          {/* ── PLAN-0059 H-2: Crosshair HUD ─────────────────────────────────
              Shows OHLCV + volume at the hovered bar in the top-left of the
              chart. Subscribes to chart.subscribeCrosshairMove. Pointer-events
              disabled so it never blocks the chart's own crosshair tracking. */}
          <CrosshairHUD
            chart={chartRef.current}
            candleSeries={seriesRef.current}
            volumeSeries={volumeSeriesRef.current}
          />

          {/* ── Skeleton loading overlay ───────────────────────────────────── */}
          {isLoading && !data && (
            <Skeleton
              className="pointer-events-none absolute inset-0 w-full"
              style={{ height: CHART_HEIGHT }}
            />
          )}

          {/* ── Refreshing indicator ───────────────────────────────────────── */}
          {isLoading && data && (
            <span
              role="status"
              aria-live="polite"
              className="pointer-events-none absolute right-2 top-2 rounded-[2px] bg-muted/80 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground"
            >
              refreshing
            </span>
          )}
        </div>
      )}
    </div>
  );
}
