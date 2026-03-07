import { useEffect, useRef } from "react";
import { createChart, type IChartApi } from "lightweight-charts";
import type { OHLCVBar } from "../lib/gateway-client";

interface OHLCVChartProps {
  data: OHLCVBar[];
  width?: number;
  height?: number;
}

export function OHLCVChart({ data, width = 600, height = 400 }: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width,
      height,
      layout: {
        background: { color: "#1e293b" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#334155" },
        horzLines: { color: "#334155" },
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    });

    candleSeries.setData(
      data.map((bar) => ({
        time: bar.date as unknown as import("lightweight-charts").Time,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
    );

    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data, width, height]);

  return <div ref={containerRef} data-testid="ohlcv-chart" />;
}
