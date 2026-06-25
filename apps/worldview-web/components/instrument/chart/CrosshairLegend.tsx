/**
 * components/instrument/chart/CrosshairLegend.tsx — hovered-candle OHLC+V legend
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 2c): hovering a candle must
 * show that candle's open/high/low/close and volume. The legacy CrosshairHUD
 * was deleted in PLAN-0090 T-B-01 along with the drawing tools; this is the
 * minimalist replacement — a single overlay row in the chart's top-left
 * corner, the TradingView convention.
 *
 * WHY PURE-PRESENTATIONAL (no chart subscription here): OHLCVChart owns the
 * lightweight-charts instance and the `subscribeCrosshairMove` wiring; this
 * component just renders whatever bar the parent says is hovered. That makes
 * it trivially unit-testable (no chart mock needed) and keeps a single owner
 * for all chart-instance side effects.
 *
 * WHO USES IT: components/instrument/chart/OHLCVChart.tsx.
 */

// WHY no "use client": pure display — props in, JSX out. The parent
// (OHLCVChart) is already a client component.

import { formatVolume } from "@/lib/utils";
import type { OHLCVBar } from "@/types/api";

export interface CrosshairLegendProps {
  /** The bar under the crosshair, or null when the pointer is off the pane. */
  readonly bar: OHLCVBar | null;
}

// WHY a local date formatter (not lib/utils formatDate): formatDate renders
// "Apr 17, 2026" — too wide for the one-row legend. The legend uses the
// compact ISO date + HH:MM (UTC) which also disambiguates intraday bars.
function fmtBarTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  // toISOString → "2026-06-10T14:35:00.000Z"; keep "2026-06-10 14:35".
  return d.toISOString().slice(0, 16).replace("T", " ");
}

// Small label+value pair. WHY font-mono tabular-nums: ADR-F-15 — every
// numeric value in the app renders in IBM Plex Mono so digits align.
function Cell({ label, value, valueClass = "text-foreground" }: {
  readonly label: string;
  readonly value: string;
  readonly valueClass?: string;
}) {
  return (
    <span className="flex items-baseline gap-0.5">
      <span className="text-[9px] uppercase text-muted-foreground">{label}</span>
      <span className={`text-[10px] font-mono tabular-nums ${valueClass}`}>{value}</span>
    </span>
  );
}

// Round-4 hardening (item 1d/1e): the OHLCVBar type promises `number`, but a
// degraded wire row can carry null/NaN — `(null).toFixed(2)` throws and NaN
// renders as the literal "NaN". One guard covers every cell.
function fmtPx(v: number): string {
  return Number.isFinite(v) ? v.toFixed(2) : "—";
}

export function CrosshairLegend({ bar }: CrosshairLegendProps) {
  // WHY return null (not a hidden div): when nothing is hovered the chart
  // canvas should be completely unobstructed — reserved-but-empty chrome over
  // the price axis area would read as a rendering glitch.
  if (!bar) return null;

  // Bullish candle (close ≥ open) renders close in teal, bearish in red —
  // same semantic tokens as the candles themselves (--positive / --negative).
  const closeClass = bar.close >= bar.open ? "text-positive" : "text-negative";

  return (
    // WHY pointer-events-none: the legend floats over the canvas; it must not
    // steal mousemove events from the chart (that would freeze the crosshair
    // the moment the pointer enters the legend).
    // WHY bg-card/90: semi-opaque panel token keeps candles faintly visible
    // underneath without compromising legibility.
    // WHY aria-hidden (Round-4 hardening, item 2): the legend re-renders at
    // pointer-move frequency — the previous role="status" + aria-live="polite"
    // made screen readers announce EVERY hovered candle, drowning out all
    // other output. The same OHLC information is exposed statically (and
    // calmly) via the chart wrapper's aria-label in OHLCVChart, so hiding
    // this mouse-only affordance from the accessibility tree loses nothing.
    <div
      data-testid="crosshair-legend"
      className="pointer-events-none absolute left-2 top-2 z-10 flex items-center gap-2 rounded-[2px] border border-border/50 bg-card/90 px-2 py-0.5"
      aria-hidden="true"
    >
      <span className="text-[9px] font-mono text-muted-foreground">{fmtBarTime(bar.timestamp)}</span>
      <Cell label="O" value={fmtPx(bar.open)} />
      <Cell label="H" value={fmtPx(bar.high)} valueClass="text-positive" />
      <Cell label="L" value={fmtPx(bar.low)} valueClass="text-negative" />
      <Cell label="C" value={fmtPx(bar.close)} valueClass={closeClass} />
      <Cell label="V" value={formatVolume(bar.volume)} />
    </div>
  );
}
