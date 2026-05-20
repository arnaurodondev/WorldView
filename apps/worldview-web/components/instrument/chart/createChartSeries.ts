/**
 * components/instrument/chart/createChartSeries.ts — lightweight-charts series factory
 *
 * WHY THIS EXISTS: useChartSeries.ts contained a large `initChart()` async function
 * that registered 15+ indicator series on the chart. Extracting the series-creation
 * logic here keeps it as a pure async factory function, making each piece easier to
 * read and test independently.
 *
 * WHY A PLAIN FUNCTION (not a hook or component): series creation is a pure
 * imperative operation on a chart API instance — no React primitives needed.
 * Plain functions are simpler, testable without a test renderer, and can be
 * called from inside a useEffect safely.
 *
 * PLAN-0059 H-1: lightweight-charts v5 pane isolation — chart.addPane() creates
 * a new independent canvas pane. Each oscillator (RSI, MACD, ATR, Stoch, OBV)
 * gets its own pane so its y-axis doesn't distort the main price scale.
 *
 * WHO USES IT: components/instrument/chart/useChartSeries.ts
 * PLAN REFERENCE: PLAN-0089 Wave D-1, PLAN-0059 H-1
 */

import type { IChartApi, ISeriesApi } from "lightweight-charts";

// ── Series handles returned to the hook ────────────────────────────────────────

export interface ChartSeriesHandles {
  // Core series
  series: ISeriesApi<"Candlestick">;
  volumeSeries: ISeriesApi<"Histogram">;
  ma50Series: ISeriesApi<"Line">;
  ma200Series: ISeriesApi<"Line">;
  // Indicator series
  rsiSeries: ISeriesApi<"Line">;
  macdLine: ISeriesApi<"Line">;
  macdSignal: ISeriesApi<"Line">;
  macdHist: ISeriesApi<"Histogram">;
  bbUpper: ISeriesApi<"Line">;
  bbMiddle: ISeriesApi<"Line">;
  bbLower: ISeriesApi<"Line">;
  atrSeries: ISeriesApi<"Line">;
  stochK: ISeriesApi<"Line">;
  stochD: ISeriesApi<"Line">;
  obvSeries: ISeriesApi<"Line">;
  vwapSeries: ISeriesApi<"Line">;
  volMA20Series: ISeriesApi<"Line">;
  vwapLineSeries: ISeriesApi<"Line">;
}

/**
 * createAllChartSeries — registers all indicator series on an already-created chart.
 *
 * WHY separate from createChart(): the chart object itself is created in
 * useChartSeries so it can be assigned to chartRef.current immediately (before
 * the series loop completes). This factory only registers series — the caller
 * sets all the resulting refs.
 *
 * WHY dynamic import instead of a top-level import: the caller (useChartSeries)
 * already dynamically imports lightweight-charts. This function receives the
 * already-resolved LineSeries / HistogramSeries constructors to avoid a second
 * dynamic import round-trip.
 */
export async function createAllChartSeries(
  chart: IChartApi,
  // The three v5 series definition values passed from the resolved dynamic import
  LineSeries: Parameters<typeof chart.addSeries>[0],
  HistogramSeries: Parameters<typeof chart.addSeries>[0],
  CandlestickSeries: Parameters<typeof chart.addSeries>[0],
): Promise<ChartSeriesHandles> {

  // ── Candlestick (main price series, pane 0) ────────────────────────────────
  const series = chart.addSeries(CandlestickSeries, {
    upColor: "#26A69A",         // --positive: teal-green (bullish)
    downColor: "#EF5350",       // --negative: muted red (bearish)
    borderUpColor: "#26A69A",
    borderDownColor: "#EF5350",
    wickUpColor: "#26A69A",
    wickDownColor: "#EF5350",
  }) as ISeriesApi<"Candlestick">;

  // ── Volume histogram (pane 0, separate price scale "volume") ──────────────
  // WHY priceScaleId "volume": separates volume from the price scale so volume
  // bars don't affect the candlestick Y range.
  // WHY scaleMargins top:0.8: volume occupies the bottom 20% of chart height.
  const volumeSeries = chart.addSeries(HistogramSeries, {
    color: "#26A69A",
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
  }) as ISeriesApi<"Histogram">;
  chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

  // ── MA50 / MA200 (pane 0, right scale, hidden by default) ─────────────────
  const ma50Series = chart.addSeries(LineSeries, {
    color: "#FFD60A",           // brand yellow
    lineWidth: 1, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;

  const ma200Series = chart.addSeries(LineSeries, {
    color: "#0EA5E9",           // sky-500 — Bloomberg convention for MA200
    lineWidth: 1, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;

  // ── Oscillator panes (PLAN-0059 H-1: each oscillator in its own pane) ──────
  // WHY chart.addPane(): v5 independent pane per oscillator; y-axis is isolated
  // from the main price scale so scale differences don't distort the chart.

  // RSI — pane 1
  chart.addPane();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rsiSeries = (chart as any).addSeries(LineSeries, {
    color: "#F59E0B", lineWidth: 1, visible: false,
  }, 1) as ISeriesApi<"Line">;

  // MACD — pane 2 (three series: line + signal + histogram)
  chart.addPane();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const macdLine = (chart as any).addSeries(LineSeries, {
    color: "#A78BFA", lineWidth: 1, visible: false,
  }, 2) as ISeriesApi<"Line">;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const macdSignal = (chart as any).addSeries(LineSeries, {
    color: "#F59E0B", lineWidth: 1, visible: false,
  }, 2) as ISeriesApi<"Line">;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const macdHist = (chart as any).addSeries(HistogramSeries, {
    color: "#26A69A", visible: false,
  }, 2) as ISeriesApi<"Histogram">;

  // Bollinger Bands — pane 0, dashed lines (overlaid on price scale)
  // WHY dashed style (lineStyle: 2): distinguishes BB from solid MA50/MA200 lines.
  const bbUpper = chart.addSeries(LineSeries, {
    color: "#6366F1", lineWidth: 1, lineStyle: 2, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;
  const bbMiddle = chart.addSeries(LineSeries, {
    color: "#6366F199", lineWidth: 1, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;
  const bbLower = chart.addSeries(LineSeries, {
    color: "#6366F1", lineWidth: 1, lineStyle: 2, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;

  // ATR — pane 3 (absolute $ volatility — incompatible with price scale)
  chart.addPane();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const atrSeries = (chart as any).addSeries(LineSeries, {
    color: "#10B981", lineWidth: 1, visible: false,
  }, 3) as ISeriesApi<"Line">;

  // Stochastic — pane 4 (%K teal, %D red)
  chart.addPane();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const stochK = (chart as any).addSeries(LineSeries, {
    color: "#26A69A", lineWidth: 1, visible: false,
  }, 4) as ISeriesApi<"Line">;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const stochD = (chart as any).addSeries(LineSeries, {
    color: "#EF5350", lineWidth: 1, visible: false,
  }, 4) as ISeriesApi<"Line">;

  // OBV — pane 5 (cumulative volume — scale incompatible with price)
  chart.addPane();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const obvSeries = (chart as any).addSeries(LineSeries, {
    color: "#38BDF8", lineWidth: 1, visible: false,
  }, 5) as ISeriesApi<"Line">;

  // VWAP — pane 0 (price scale, dotted pink line)
  // WHY pink (#EC4899) + dotted: VWAP is on the price scale but isn't a MA.
  // Dotted line + pink colour distinguish it from MA50 (solid yellow) and MA200 (solid blue).
  const vwapSeries = chart.addSeries(LineSeries, {
    color: "#EC4899", lineWidth: 1, lineStyle: 1, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;

  // Volume MA20 — overlaid on the volume scale (lime-500)
  const volMA20Series = chart.addSeries(LineSeries, {
    color: "#84CC16", lineWidth: 1, priceScaleId: "volume", visible: false,
  }) as ISeriesApi<"Line">;

  // VWAP Line (volume submenu variant) — same VWAP data, different entry point
  // WHY duplicate: "VWAP" in Indicators is for advanced users; "VWAP Line" in
  // the Vol submenu is labeled more descriptively for less experienced users.
  const vwapLineSeries = chart.addSeries(LineSeries, {
    color: "#EC4899", lineWidth: 1, lineStyle: 1, priceScaleId: "right", visible: false,
  }) as ISeriesApi<"Line">;

  return {
    series, volumeSeries, ma50Series, ma200Series,
    rsiSeries, macdLine, macdSignal, macdHist,
    bbUpper, bbMiddle, bbLower,
    atrSeries, stochK, stochD,
    obvSeries, vwapSeries, volMA20Series, vwapLineSeries,
  };
}
