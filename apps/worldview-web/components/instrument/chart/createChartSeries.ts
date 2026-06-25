/**
 * components/instrument/chart/createChartSeries.ts — lightweight-charts series factory
 *
 * WHY THIS EXISTS: useChartSeries.ts manages React state/refs; the imperative
 * "register series on the chart" work lives here as plain functions so it can
 * be unit-tested without a React renderer.
 *
 * ── THE 2026-06-10 PANE REBUILD (root cause of the "broken chart" bug) ──────
 *
 * The previous implementation called `chart.addPane()` 5 times at init (one
 * pane per oscillator: RSI/MACD/ATR/STOCH/OBV) and then tried to collapse the
 * unused panes with `pane.setOptions({ height: 0 })`. TWO fatal problems:
 *
 *   1. `IPaneApi` has NO `setOptions()` method in lightweight-charts v5 —
 *      the real API is `setHeight(number)`. Because the call was written as
 *      `pane?.setOptions?.({...})` (optional chaining), it SILENTLY no-oped.
 *      Result: five permanent, empty panes at default stretch heights — the
 *      price pane squeezed into the top ~15% of the canvas, three+ giant
 *      blank panes below it, and a stray "0.00" axis label floating mid-page.
 *
 *   2. Even with `setHeight(0)`, the library clamps pane heights to
 *      MIN_PANE_HEIGHT = 30px (verified in the v5.2.0 source), so "collapse
 *      to zero" can never work. The old comment claiming "v5 has no
 *      removePane() API" is also wrong: `chart.removePane(index)` exists and
 *      is typed in 5.2.0.
 *
 * NEW DESIGN — LAZY PANES:
 *   - `createCoreSeries()` registers ONLY pane-0 series at init (candles,
 *     volume overlay, MAs, Bollinger, VWAP). Zero extra panes are created, so
 *     the price chart owns 100% of the canvas by default.
 *   - `createOscillatorSeries()` is called ON DEMAND when the user enables an
 *     oscillator. It creates the series with the typed 3-argument
 *     `chart.addSeries(def, opts, paneIndex)` overload where
 *     `paneIndex = chart.panes().length` — lightweight-charts auto-creates
 *     the pane. The pane height is then pinned via the REAL
 *     `pane.setHeight(OSC_PANE_HEIGHT)` API.
 *   - When the user disables the oscillator, useChartSeries calls
 *     `chart.removePane(pane.paneIndex())` — the pane (and its series) are
 *     destroyed and the price pane reclaims the space.
 *
 * WHO USES IT: components/instrument/chart/useChartSeries.ts
 * PLAN REFERENCE: PRD-0088 Quote-tab redesign, Wave-2 chart rebuild.
 */

import type {
  IChartApi,
  IPaneApi,
  ISeriesApi,
  SeriesDefinition,
  SeriesType,
  Time,
} from "lightweight-charts";

// ── Series-definition bag ─────────────────────────────────────────────────────
//
// WHY a bag object: the chart library is dynamically imported (it touches
// `window` at module scope). useChartSeries resolves the import ONCE and hands
// the three series-definition constants to every factory call — no second
// dynamic import round-trip, and the lazy oscillator path (which runs long
// after init) can reuse the same resolved definitions from a ref.

export interface SeriesDefs {
  readonly LineSeries: SeriesDefinition<"Line">;
  readonly HistogramSeries: SeriesDefinition<"Histogram">;
  readonly CandlestickSeries: SeriesDefinition<"Candlestick">;
}

// ── Pane height constant ──────────────────────────────────────────────────────
//
// WHY 90px: industry convention for oscillator sub-panes — tall enough to read
// the line shape, short enough that two simultaneous oscillators still leave
// the price pane with ≥60% of a typical 600px canvas.

export const OSC_PANE_HEIGHT = 90;

// ── Core (pane 0) series handles ─────────────────────────────────────────────

export interface CoreSeriesHandles {
  /** Candlestick price series — the chart's centrepiece. */
  series: ISeriesApi<"Candlestick">;
  /** Volume histogram — pane-0 OVERLAY on its own "volume" price scale. */
  volumeSeries: ISeriesApi<"Histogram">;
  ma50Series: ISeriesApi<"Line">;
  ma200Series: ISeriesApi<"Line">;
  bbUpper: ISeriesApi<"Line">;
  bbMiddle: ISeriesApi<"Line">;
  bbLower: ISeriesApi<"Line">;
  /** VWAP overlay (Indicators menu entry). */
  vwapSeries: ISeriesApi<"Line">;
  /** Volume MA20 overlay on the volume scale. */
  volMA20Series: ISeriesApi<"Line">;
  /** VWAP overlay (Vol submenu entry — same data, second toggle). */
  vwapLineSeries: ISeriesApi<"Line">;
}

/**
 * createCoreSeries — registers all PANE-0 series (price + overlays) on the
 * chart. Creates NO additional panes — see the module doc for why that is
 * the load-bearing design decision.
 */
export function createCoreSeries(chart: IChartApi, defs: SeriesDefs): CoreSeriesHandles {
  // ── Candlestick (main price series) ────────────────────────────────────────
  const series = chart.addSeries(defs.CandlestickSeries, {
    upColor: "#26A69A",         // --positive: teal-green (bullish)
    downColor: "#EF5350",       // --negative: muted red (bearish)
    borderUpColor: "#26A69A",
    borderDownColor: "#EF5350",
    wickUpColor: "#26A69A",
    wickDownColor: "#EF5350",
  });

  // ── Volume histogram (pane-0 overlay, separate "volume" price scale) ──────
  // WHY an overlay (not its own pane): the redesign spec allows either a 30%
  // bottom pane or an overlay; the overlay keeps the price axis full-height
  // (more vertical resolution for candles) and is the TradingView default.
  // WHY scaleMargins top:0.72: volume occupies the bottom ~28% of the canvas,
  // approximating the requested "price ~70% / volume ~30%" split without
  // sacrificing price-pane pixels to a hard divider.
  const volumeSeries = chart.addSeries(defs.HistogramSeries, {
    color: "#26A69A",
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
  });
  chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.72, bottom: 0 } });

  // ── Moving averages (pane 0, right scale, hidden until toggled) ───────────
  const ma50Series = chart.addSeries(defs.LineSeries, {
    color: "#FFD60A",           // brand yellow — MA50 convention
    lineWidth: 1, priceScaleId: "right", visible: false,
  });
  const ma200Series = chart.addSeries(defs.LineSeries, {
    color: "#0EA5E9",           // sky-500 — Bloomberg convention for MA200
    lineWidth: 1, priceScaleId: "right", visible: false,
  });

  // ── Bollinger Bands (pane 0, dashed to distinguish from solid MAs) ────────
  const bbUpper = chart.addSeries(defs.LineSeries, {
    color: "#6366F1", lineWidth: 1, lineStyle: 2, priceScaleId: "right", visible: false,
  });
  const bbMiddle = chart.addSeries(defs.LineSeries, {
    color: "#6366F199", lineWidth: 1, priceScaleId: "right", visible: false,
  });
  const bbLower = chart.addSeries(defs.LineSeries, {
    color: "#6366F1", lineWidth: 1, lineStyle: 2, priceScaleId: "right", visible: false,
  });

  // ── VWAP (pane 0, dotted pink — visually distinct from both MAs) ──────────
  const vwapSeries = chart.addSeries(defs.LineSeries, {
    color: "#EC4899", lineWidth: 1, lineStyle: 1, priceScaleId: "right", visible: false,
  });

  // ── Volume MA20 (overlaid on the volume scale, lime) ──────────────────────
  const volMA20Series = chart.addSeries(defs.LineSeries, {
    color: "#84CC16", lineWidth: 1, priceScaleId: "volume", visible: false,
  });

  // ── VWAP Line (Vol-submenu duplicate of VWAP — separate toggle) ───────────
  const vwapLineSeries = chart.addSeries(defs.LineSeries, {
    color: "#EC4899", lineWidth: 1, lineStyle: 1, priceScaleId: "right", visible: false,
  });

  return {
    series, volumeSeries, ma50Series, ma200Series,
    bbUpper, bbMiddle, bbLower, vwapSeries, volMA20Series, vwapLineSeries,
  };
}

// ── Lazy oscillator panes ─────────────────────────────────────────────────────

/** The five indicators that render in their own sub-pane (not pane-0 overlays). */
export type OscillatorId = "RSI" | "MACD" | "ATR" | "STOCHASTIC" | "OBV";

/**
 * OscillatorHandles — everything useChartSeries needs to feed data into a live
 * oscillator pane and to destroy it on disable.
 *
 * WHY keep the `pane` handle: removal needs the CURRENT pane index, which can
 * shift when another oscillator's pane is removed first. `pane.paneIndex()`
 * is always live, so we never hold a stale numeric index.
 */
export interface OscillatorHandles {
  readonly id: OscillatorId;
  readonly pane: IPaneApi<Time>;
  /** 1-3 series depending on the oscillator (MACD has line+signal+histogram). */
  readonly lines: readonly ISeriesApi<SeriesType>[];
}

/**
 * createOscillatorSeries — create the pane + series for one oscillator ON
 * DEMAND (when the user toggles it on).
 *
 * HOW THE PANE IS CREATED: passing `paneIndex = chart.panes().length` to the
 * typed 3-argument addSeries overload makes lightweight-charts auto-create a
 * new pane at the bottom of the stack. We then pin its height with the REAL
 * v5 API (`pane.setHeight`) — see the module doc for the setOptions() bug
 * this replaces.
 */
export function createOscillatorSeries(
  chart: IChartApi,
  defs: SeriesDefs,
  id: OscillatorId,
): OscillatorHandles {
  // Next free pane slot — pane 0 is the price pane, so the first oscillator
  // lands at index 1, the second at 2, etc.
  const paneIndex = chart.panes().length;

  // WHY visible:true here (the old code created everything visible:false):
  // lazy creation means "created" === "enabled" — there is no hidden state.
  const lines: ISeriesApi<SeriesType>[] = [];
  switch (id) {
    case "RSI":
      lines.push(chart.addSeries(defs.LineSeries, { color: "#F59E0B", lineWidth: 1 }, paneIndex));
      break;
    case "MACD":
      // Order matters for z-stacking: histogram first (background), then lines.
      lines.push(chart.addSeries(defs.HistogramSeries, { color: "#26A69A" }, paneIndex));
      lines.push(chart.addSeries(defs.LineSeries, { color: "#A78BFA", lineWidth: 1 }, paneIndex));
      lines.push(chart.addSeries(defs.LineSeries, { color: "#F59E0B", lineWidth: 1 }, paneIndex));
      break;
    case "ATR":
      lines.push(chart.addSeries(defs.LineSeries, { color: "#10B981", lineWidth: 1 }, paneIndex));
      break;
    case "STOCHASTIC":
      // %K teal, %D red — the universal stochastic colour pair.
      lines.push(chart.addSeries(defs.LineSeries, { color: "#26A69A", lineWidth: 1 }, paneIndex));
      lines.push(chart.addSeries(defs.LineSeries, { color: "#EF5350", lineWidth: 1 }, paneIndex));
      break;
    case "OBV":
      lines.push(chart.addSeries(defs.LineSeries, { color: "#38BDF8", lineWidth: 1 }, paneIndex));
      break;
  }

  // The pane now exists (addSeries auto-created it) — pin its height.
  const pane = chart.panes()[paneIndex];
  pane.setHeight(OSC_PANE_HEIGHT);

  return { id, pane, lines };
}

/**
 * removeOscillatorPane — destroy an oscillator's pane (and all its series).
 *
 * WHY remove the PANE (not just the series): `chart.removePane(i)` is the v5
 * primitive that gives the reclaimed height back to the price pane. Removing
 * only the series would leave a 90px empty pane behind — exactly the class of
 * bug this rebuild eliminates.
 */
export function removeOscillatorPane(chart: IChartApi, handles: OscillatorHandles): void {
  // paneIndex() is read LIVE because earlier removals shift later indexes.
  chart.removePane(handles.pane.paneIndex());
}
