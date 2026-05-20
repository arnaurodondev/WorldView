/**
 * SessionStatsStrip — OHLCV session statistics below the chart
 *
 * WHY THIS EXISTS: The instrument overview chart does not have inline axis labels
 * for O/H/L/V/VWAP — showing them as a dedicated strip below the chart is the
 * Bloomberg convention. Traders glance at this strip to understand the session's
 * range before making a decision.
 *
 * WHY NOT from Quote type: The Quote response (WebSocket live price) does NOT
 * include open, high, or low — only last_price, bid, ask, volume. Session OHLCV
 * data comes from the last bar of the OHLCV response, which does include all fields.
 * Passing props from the parent who owns the OHLCV data is the correct data flow.
 *
 * WHY high = text-positive and low = text-negative: This is the Bloomberg Terminal
 * convention — the session high is "good" (bulls pushed the price up), the session
 * low is "bad" (bears pushed the price down). The semantic color helps traders
 * instantly understand where in the day range the current price sits.
 *
 * WHO USES IT: instrument/[entityId]/page.tsx — below the OHLCVChart component,
 *              above the timeframe selector bar.
 * DATA SOURCE: Props from parent (last OHLCV bar) — no independent fetch.
 * DESIGN REFERENCE: PRD-0031 §9 Instrument Detail, §13 New Components (SessionStatsStrip)
 */

// WHY no "use client": this is a pure display component — no hooks, no browser APIs.
// Props flow in from the parent (server or client), making this a Server Component.
// The parent (OHLCVChart / InstrumentPage) is already "use client".

import { formatMarketCap } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface SessionStatsStripProps {
  /** Session open price from last OHLCV bar — null if data not yet loaded */
  open: number | null;
  /** Session high price from last OHLCV bar — rendered in text-positive (green) */
  high: number | null;
  /** Session low price from last OHLCV bar — rendered in text-negative (red) */
  low: number | null;
  /** Session volume from last OHLCV bar — abbreviated (e.g., "43.2M") */
  volume: number | null;
  /** Volume-weighted average price — optional, shown only when available */
  vwap?: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * fmtPrice — format a price to 2 decimal places.
 * WHY not formatMarketCap: prices need decimal precision ($171.12), not
 * abbreviated notation ($171M which would be wrong for a stock price).
 */
function fmtPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toFixed(2);
}

/**
 * fmtVolume — abbreviate volume using the formatMarketCap utility (without $ prefix).
 * WHY reuse formatMarketCap: same magnitude abbreviation logic (M/B/T suffixes).
 * The $ prefix from formatMarketCap is stripped because volume is unitless shares.
 */
function fmtVolume(value: number | null | undefined): string {
  if (value == null) return "—";
  // WHY strip $ prefix: formatMarketCap adds "$" for dollar amounts.
  // Volume is in shares (unitless), not dollars — strip the currency symbol.
  return formatMarketCap(value).replace("$", "");
}

// ── Stat item sub-component ───────────────────────────────────────────────────

/**
 * Stat — a single label:value pair in the session stats strip.
 *
 * WHY separate (not inline): ensures consistent sizing across all 5 stats.
 * The valueClass prop allows per-stat color (high=positive, low=negative).
 */
function Stat({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <span className="flex items-baseline gap-1 shrink-0">
      {/* PLAN-0090 T-B-01 spec: 10px uppercase muted label, 11px mono tabular
          value. Uppercase + 1px size gap mimics the Bloomberg O/H/L/V row. */}
      <span className="text-[10px] uppercase text-muted-foreground font-mono">{label}</span>
      <span className={`text-[11px] font-mono tabular-nums ${valueClass}`}>{value}</span>
    </span>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SessionStatsStrip — 22px height bar showing O/H/L/V/VWAP (T-B-01 density spec).
 *
 * Rendered as a pure display row — no interactive elements, no state,
 * no data fetching. The parent is responsible for providing last OHLCV bar data.
 */
export function SessionStatsStrip({
  open,
  high,
  low,
  volume,
  vwap,
}: SessionStatsStripProps) {
  return (
    // PLAN-0090 T-B-01 spec: strip is exactly 22px tall (h-[22px]) to match the
    // standard data-row density used across the Quote tab. bg-background avoids
    // the seam against the chart canvas (T-B-2-01). px-3 mirrors metrics rows.
    // overflow-x-auto + min-w-0 retained from PLAN-0050 T-F-6-10 so the O/H/L/V
    // cluster scrolls horizontally on tablet-width viewports rather than clipping.
    <div
      className="flex h-[22px] min-w-0 items-center gap-4 overflow-x-auto border-b border-border/50 bg-background px-3"
      aria-label="Session statistics"
    >
      <Stat label="O" value={fmtPrice(open)} />

      {/* Separator — thin vertical rule between stats */}
      <span className="text-[10px] text-border" aria-hidden="true">│</span>

      {/* WHY text-positive for High: Bloomberg convention — session high = bullish push */}
      <Stat label="H" value={fmtPrice(high)} valueClass="text-positive" />

      <span className="text-[10px] text-border" aria-hidden="true">│</span>

      {/* WHY text-negative for Low: Bloomberg convention — session low = bearish push */}
      <Stat label="L" value={fmtPrice(low)} valueClass="text-negative" />

      <span className="text-[10px] text-border" aria-hidden="true">│</span>

      {/* WHY fmtVolume (not fmtPrice): volume is in shares (43.2M), not dollars */}
      <Stat label="V" value={fmtVolume(volume)} />

      {/* WHY conditional: VWAP may not be in older OHLCV bars — hide rather than
       * show "—" for an optional field that most users only care about intraday. */}
      {vwap != null && (
        <>
          <span className="text-[10px] text-border" aria-hidden="true">│</span>
          <Stat label="VWAP" value={fmtPrice(vwap)} />
        </>
      )}
    </div>
  );
}
