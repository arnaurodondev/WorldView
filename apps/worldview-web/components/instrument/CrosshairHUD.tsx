/**
 * components/instrument/CrosshairHUD.tsx — OHLCV crosshair HUD overlay
 *
 * WHY THIS EXISTS: Bloomberg/TradingView charts show O-H-L-C+V values at the
 * hovered bar in a fixed corner of the chart — the trader's eye never leaves
 * the price action while reading exact numbers. PLAN-0059 H-2 adds this to
 * worldview's OHLCVChart, which previously showed only the floating crosshair
 * line with no numeric callout.
 *
 * SUBSCRIBES via chart.subscribeCrosshairMove. When the crosshair leaves the
 * chart area, MouseEventParams.point is undefined and we hide the HUD.
 *
 * STYLED to match the institutional terminal density: 11px tabular-nums,
 * font-mono, color-coded change pill.
 */

"use client";

import * as React from "react";
import type { IChartApi, ISeriesApi, MouseEventParams, UTCTimestamp } from "lightweight-charts";
import { cn } from "@/lib/utils";

interface CrosshairHUDProps {
  chart: IChartApi | null;
  candleSeries: ISeriesApi<"Candlestick"> | null;
  volumeSeries: ISeriesApi<"Histogram"> | null;
  /** Optional className for positioning. Defaults to top-left over chart. */
  className?: string;
}

interface HUDData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

function formatTime(t: number): string {
  // Unix seconds → "MMM DD" or "MMM DD HH:MM" for intraday.
  const d = new Date(t * 1000);
  const day = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  // If the time has a non-zero hour, add HH:MM (intraday timeframes).
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  if (h === 0 && m === 0) return day;
  return `${day} ${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function formatVol(v: number | null): string {
  if (v === null) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

export function CrosshairHUD({ chart, candleSeries, volumeSeries, className }: CrosshairHUDProps) {
  const [data, setData] = React.useState<HUDData | null>(null);

  React.useEffect(() => {
    if (!chart || !candleSeries) return;

    const handler = (param: MouseEventParams) => {
      // Outside chart area or no time → hide HUD.
      if (!param.point || param.time == null) {
        setData(null);
        return;
      }
      // Series data Map keyed by series instance.
      const candleData = param.seriesData.get(candleSeries) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      if (!candleData) {
        setData(null);
        return;
      }
      const volData = volumeSeries
        ? (param.seriesData.get(volumeSeries) as { value?: number } | undefined)
        : undefined;

      setData({
        time: param.time as UTCTimestamp,
        open: candleData.open,
        high: candleData.high,
        low: candleData.low,
        close: candleData.close,
        volume: volData?.value ?? null,
      });
    };

    chart.subscribeCrosshairMove(handler);
    return () => chart.unsubscribeCrosshairMove(handler);
  }, [chart, candleSeries, volumeSeries]);

  if (!data) return null;

  const change = data.close - data.open;
  const changePct = data.open > 0 ? (change / data.open) * 100 : 0;
  const isPos = change > 0;
  const isNeg = change < 0;

  return (
    <div
      role="status"
      aria-live="off"
      className={cn(
        // Top-left over the chart. Pointer-events-none so it never blocks the
        // chart's own crosshair tracking. WHY backdrop-blur + bg-card/90:
        // legibility on top of dark candlesticks without covering them.
        "pointer-events-none absolute left-9 top-2 z-20 rounded-[2px] border border-border bg-card/90 px-2 py-1 font-mono text-[10px] tabular-nums shadow-md backdrop-blur-sm",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">{formatTime(data.time)}</span>
        <span className={cn(
          "rounded-[2px] px-1",
          isPos && "bg-positive/15 text-positive",
          isNeg && "bg-negative/15 text-negative",
          !isPos && !isNeg && "text-muted-foreground",
        )}>
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)} ({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-foreground">
        <span><span className="text-muted-foreground">O</span> {data.open.toFixed(2)}</span>
        <span><span className="text-muted-foreground">H</span> {data.high.toFixed(2)}</span>
        <span><span className="text-muted-foreground">L</span> {data.low.toFixed(2)}</span>
        <span className="font-semibold"><span className="text-muted-foreground font-normal">C</span> {data.close.toFixed(2)}</span>
        <span className="text-muted-foreground">V {formatVol(data.volume)}</span>
      </div>
    </div>
  );
}
