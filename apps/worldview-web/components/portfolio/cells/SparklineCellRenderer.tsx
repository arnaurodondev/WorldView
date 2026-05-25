/**
 * SparklineCellRenderer — AG Grid cell renderer: 60×16px sparkline from F1 primitive.
 *
 * WHY THIS EXISTS: Each holdings row needs a 14-day close-price sparkline to show
 * momentum at a glance. AG Grid requires a custom cell renderer to embed an SVG
 * component. The sparkline uses the F1 <Sparkline> primitive (60×16, trend="auto")
 * which applies 3-state trend tinting (bull/bear/neutral) automatically.
 * WHO USES IT: ag-holdings-columns.tsx SPARK column cellRenderer.
 * DATA SOURCE: holdingsSeries prop from parent context — Record<ticker, number[]>
 * passed via AG Grid context (params.context.holdingsSeries). When no context is
 * provided (e.g. in tests or before data loads), renders "—" placeholder.
 * DESIGN REFERENCE: PRD-0089 W2 §4.11, V7
 */

import type { ICellRendererParams } from "ag-grid-community";
import { Sparkline } from "@/components/primitives/Sparkline";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

interface SparklineCellContext {
  /** Keyed by ticker, values are close-price series (typically 14 bars of 1D OHLCV). */
  holdingsSeries: Record<string, number[]>;
}

export function SparklineCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // WHY pinned-row guard: the totals footer has no meaningful sparkline — it
  // aggregates multiple instruments with incompatible scales.
  if (params.node?.rowPinned === "bottom") return null;

  // WHY access ticker from params.data.h.ticker rather than params.value:
  // the SPARK colDef uses field="h" (the whole Holding object). We need the
  // ticker string to look up the series in the context.
  const ticker = params.data?.h.ticker;
  const context = params.context as SparklineCellContext | undefined;
  const series = ticker ? (context?.holdingsSeries?.[ticker] ?? []) : [];

  if (!ticker || series.length < 2) {
    // Loading or missing data — em-dash placeholder avoids layout shift.
    // WHY em-dash (not skeleton): AG Grid re-renders the cell on data change;
    // a skeleton would flash and disappear, which is more jarring than a dash.
    return (
      <span className="font-mono text-[11px] text-muted-foreground">—</span>
    );
  }

  return (
    // WHY flex + items-center: sparkline SVG should be vertically centered in
    // the 20px row. Without flex the SVG baseline-aligns to the text baseline
    // which pushes it ~2px too low.
    <div className="flex items-center h-full">
      <Sparkline data={series} width={60} height={16} trend="auto" label={`${ticker} trend`} />
    </div>
  );
}
