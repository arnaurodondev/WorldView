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
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx
 * DATA SOURCE: S9 GET /v1/ohlcv/{instrumentId}?timeframe=1D
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail chart, canvas State B
 */

"use client";
// WHY "use client": uses useEffect (DOM manipulation for chart init),
// useRef (chart instance), useState (timeframe selection), useQuery.

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
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
  upColor: "#26A69A",       // --positive: teal-green (bullish candles)
  downColor: "#EF5350",     // --negative: muted red (bearish candles)
  borderUpColor: "#26A69A", // candle body border — matches fill
  borderDownColor: "#EF5350",
  wickUpColor: "#26A69A",   // wick color — matches candle color for clarity
  wickDownColor: "#EF5350",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function OHLCVChart({ instrumentId, initialBars }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  // WHY chartError state: if the dynamic import for lightweight-charts fails (e.g.,
  // CDN down, bundle corruption, network timeout), we show a fallback instead of
  // blank space. Financial UI must NEVER silently fail — blank charts erode trust.
  const [chartError, setChartError] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  // WHY useRef for chart: preserves chart instance across re-renders without
  // causing re-renders itself (unlike useState which would create a loop)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);

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
    let chart: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any

    async function initChart() {
      try {
        const { createChart } = await import("lightweight-charts");

        // WHY null check after await: dynamic import is async — by the time it
        // resolves, the component may have unmounted and the ref may be null.
        // Without this guard, initChart throws on unmount (e.g., in tests or
        // fast navigation). This is a defensive pattern for async effects.
        if (!containerRef.current) return;

        chart = createChart(containerRef.current, {
          width: containerRef.current.clientWidth,
          // WHY 360 (was 280): terminal charts need at least 360px height to show
          // meaningful price action. 280px is too short for candlestick readability
          // on instruments with tight day-ranges. 360px matches PRD-0028 §6.5 spec.
          height: 360,
          layout: CHART_THEME.layout,
          grid: CHART_THEME.grid,
          crosshair: CHART_THEME.crosshair,
          rightPriceScale: {
            // WHY #111113 (--card) not #27272A (--border): the price scale border
            // is a structural edge between the chart area and the price labels.
            // Using the card color keeps it recessive — the data, not the frame,
            // should draw the eye.
            borderColor: "#111113",  // --card: Terminal Dark panel background
          },
          timeScale: {
            borderColor: "#111113",  // --card: matches price scale border
            timeVisible: true,
          },
        });

        const series = chart.addCandlestickSeries({
          upColor: CHART_THEME.upColor,
          downColor: CHART_THEME.downColor,
          borderUpColor: CHART_THEME.borderUpColor,
          borderDownColor: CHART_THEME.borderDownColor,
          wickUpColor: CHART_THEME.wickUpColor,
          wickDownColor: CHART_THEME.wickDownColor,
        });

        chartRef.current = chart;
        seriesRef.current = series;
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
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart?.remove();
      chartRef.current = null;
      seriesRef.current = null;
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

    if (formattedBars.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [data?.bars]);

  return (
    <div>
      {/* Timeframe selector */}
      <div className="mb-2 flex gap-1">
        {/* WHY this exact order: mirrors conventional charting toolbar order —
           intraday (5M, 1H) → daily → weekly → monthly. 1W/1M are added here
           because S3 ingests weekly/monthly EODHD bars as first-class timeframes. */}
        {(["5M", "1H", "1D", "1W", "1M"] as Timeframe[]).map((tf) => (
          <button
            key={tf}
            onClick={() => setTimeframe(tf)}
            className={`rounded-[2px] px-2 py-0.5 text-xs font-medium transition-colors ${
              timeframe === tf
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tf}
          </button>
        ))}
      </div>

      {/* Chart error fallback — shown when lightweight-charts fails to load */}
      {chartError && (
        <div className="flex h-[360px] items-center justify-center rounded-[2px] border border-border bg-card">
          <p className="text-sm text-muted-foreground">Chart unavailable</p>
        </div>
      )}

      {/* Chart container — only rendered when no error */}
      {!chartError && isLoading && !data && (
        <Skeleton className="h-[360px] w-full" />
      )}
      {!chartError && (
        <div
          ref={containerRef}
          className="w-full"
          style={{ opacity: isLoading ? 0.5 : 1 }}
        />
      )}
    </div>
  );
}
