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
 * WHY 280px chart height (was 360px): Volume uses scaleMargins to occupy the
 * bottom 20% of the chart area. At 280px total, the candlestick area has ~224px
 * and volume has ~56px — matching TradingView's default proportion.
 *
 * WHO USES IT: OverviewLayout (within the chart+sidebar upper section)
 * DATA SOURCE: S9 GET /v1/ohlcv/{instrumentId}?timeframe=1D
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail chart, PLAN-0041 §T-C-2-02
 */

"use client";
// WHY "use client": uses useEffect (DOM manipulation for chart init),
// useRef (chart instance), useState (timeframe + toolbar controls).

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import type { OHLCVBar } from "@/types/api";

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

// ── MA computation ─────────────────────────────────────────────────────────────

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

// ── Component ─────────────────────────────────────────────────────────────────

export function OHLCVChart({ instrumentId, initialBars }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  // ── Toolbar toggle state ───────────────────────────────────────────────────
  // WHY default showVolume=true: volume is standard in all financial charting UIs.
  // MA50/MA200 default off — adding them is an intentional analyst decision.
  const [showVolume, setShowVolume] = useState(true);
  const [showMA50, setShowMA50] = useState(false);
  const [showMA200, setShowMA200] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // WHY chartError state: if the dynamic import for lightweight-charts fails (e.g.,
  // CDN down, bundle corruption, network timeout), we show a fallback instead of
  // blank space. Financial UI must NEVER silently fail — blank charts erode trust.
  const [chartError, setChartError] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  // WHY useRef for chart + series: preserves instances across re-renders without
  // causing re-renders themselves (unlike useState which would create a loop).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);          // candlestick series
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const volumeSeriesRef = useRef<any>(null);    // volume histogram series
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ma50SeriesRef = useRef<any>(null);      // MA50 line series
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ma200SeriesRef = useRef<any>(null);     // MA200 line series

  const { data, isLoading } = useQuery({
    queryKey: ["ohlcv", instrumentId, timeframe],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId, { timeframe }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 60_000, // WHY 1min: OHLCV bars don't change within the same candle period
    // WHY placeholderData: show the 1D bars from CompanyOverview immediately
    placeholderData: initialBars && timeframe === "1D"
      ? { instrument_id: instrumentId, ticker: "", timeframe: "1D", bars: initialBars }
      : undefined,
  });

  // ── Chart init & cleanup ───────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    // WHY dynamic import: lightweight-charts uses browser APIs unavailable at SSR.
    // Dynamic import ensures it only loads client-side.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let chart: any = null;

    async function initChart() {
      try {
        const { createChart } = await import("lightweight-charts");

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
        const series = chart.addCandlestickSeries({
          upColor: "#26A69A",         // --positive: teal-green (bullish)
          downColor: "#EF5350",       // --negative: muted red (bearish)
          borderUpColor: "#26A69A",
          borderDownColor: "#EF5350",
          wickUpColor: "#26A69A",
          wickDownColor: "#EF5350",
        });

        chartRef.current = chart;
        seriesRef.current = series;

        // ── Volume histogram series ────────────────────────────────────────
        // WHY priceScaleId "volume": separates volume from the price scale,
        // preventing volume bars from affecting the candlestick Y range.
        // WHY scaleMargins top:0.8: volume occupies the bottom 20% of chart
        // height (~56px at CHART_HEIGHT=280) — the candlestick area uses 80%.
        const volumeSeries = chart.addHistogramSeries({
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
        const ma50Series = chart.addLineSeries({
          color: "#FFD60A",
          lineWidth: 1,
          priceScaleId: "right",      // same scale as candlesticks
          visible: false,             // off by default — analyst opt-in
        });
        ma50SeriesRef.current = ma50Series;

        // ── MA200 line series (sky-500, default hidden) ────────────────────
        // WHY #0EA5E9 (sky-500): distinct from MA50 yellow; blue is a common
        // convention for MA200 in Bloomberg and TradingView.
        const ma200Series = chart.addLineSeries({
          color: "#0EA5E9",
          lineWidth: 1,
          priceScaleId: "right",
          visible: false,             // off by default — analyst opt-in
        });
        ma200SeriesRef.current = ma200Series;

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
      if (chartRef.current && containerRef.current && !isFullscreen) {
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
    };
  }, []); // WHY empty deps: chart init runs once on mount, cleanup on unmount

  // ── Update chart data when bars change ────────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current || !data?.bars) return;

    // Convert ISO timestamps to Unix time (lightweight-charts expects seconds)
    const formattedBars = data.bars.map((bar) => ({
      time: Math.floor(new Date(bar.timestamp).getTime() / 1000) as number,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    // WHY setData (not updateData): timeframe switch replaces the full dataset
    seriesRef.current.setData(formattedBars);

    // ── Volume data ────────────────────────────────────────────────────────
    // WHY per-bar color: up-close bars → transparent green, down-close → transparent red.
    // WHY 40 alpha hex (25%): full opacity volume bars overpower the candlesticks.
    // Semi-transparent bars keep volume visually secondary to price action.
    if (volumeSeriesRef.current) {
      const volumeData = data.bars.map((bar, i) => ({
        time: formattedBars[i].time,
        value: bar.volume ?? 0,
        color: bar.close >= bar.open ? "#26A69A40" : "#EF535040",
      }));
      volumeSeriesRef.current.setData(volumeData);
    }

    // ── MA50 data ──────────────────────────────────────────────────────────
    // WHY guard with formattedBars.length: computeMA returns [] if not enough bars.
    // setData([]) is valid and simply clears the series.
    if (ma50SeriesRef.current) {
      ma50SeriesRef.current.setData(computeMA(formattedBars, 50));
    }

    // ── MA200 data ─────────────────────────────────────────────────────────
    // WHY no special handling for <200 bars: computeMA returns [], which is valid.
    // The MA200 line simply doesn't render when the timeframe has <200 bars.
    if (ma200SeriesRef.current) {
      ma200SeriesRef.current.setData(computeMA(formattedBars, 200));
    }

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

        {/* Chart overlay controls — right side of toolbar */}
        <ChartToolbar
          showVolume={showVolume}
          onToggleVolume={() => setShowVolume((v) => !v)}
          showMA50={showMA50}
          onToggleMA50={() => setShowMA50((v) => !v)}
          showMA200={showMA200}
          onToggleMA200={() => setShowMA200((v) => !v)}
          isFullscreen={isFullscreen}
          onFullscreen={() => setIsFullscreen((v) => !v)}
        />
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

      {/* ── Loading skeleton ────────────────────────────────────────────── */}
      {!chartError && isLoading && !data && (
        <Skeleton style={{ height: CHART_HEIGHT }} className="w-full" />
      )}

      {/* ── Chart container ─────────────────────────────────────────────── */}
      {/* WHY flex-1 when fullscreen: the container should fill all remaining height
          in the fixed overlay. In normal mode, the chart height is controlled by
          CHART_HEIGHT passed to lightweight-charts via applyOptions. */}
      {!chartError && (
        <div
          ref={containerRef}
          className={`w-full ${isFullscreen ? "flex-1" : ""}`}
          style={{ opacity: isLoading ? 0.5 : 1 }}
        />
      )}
    </div>
  );
}
