/**
 * components/instrument/quote/strips/IntradayStatsBand.tsx
 * — 6-stat intraday band (W5-T-10)
 *
 * WHY THIS EXISTS:
 *   Session-level statistics that change during market hours need their own
 *   strip below the multi-period returns. VWAP, ATR, RSI, GAP%, Premarket
 *   and Short Interest give traders the intraday context they check on every
 *   terminal session open.
 *
 * DATA SOURCE: GET /v1/fundamentals/{id}/intraday-stats (T-S9-02).
 *   Computed by S9 from 5m + daily OHLCV bars + technicals snapshot.
 *   All fields are nullable (fail-soft: S9 returns 200 with nulls on S3 error).
 *
 * DESIGN DECISIONS:
 *   - `<div data-table-grid>` parent → 20px row height (Δ4, F1 §16.3).
 *   - PREM cell hidden after-hours when premarket_high === null (Δ — §7.4 empty state).
 *   - 6 equal-width cells; PREM replaced by a spacer div when hidden so the
 *     remaining 5 cells still span the full strip width.
 *   - `text-[10px]` labels (F1 floor, Δ2). `text-[11px] font-mono tabular-nums` values.
 *   - No `rounded-*` (Δ3, F1 rounded=0).
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass). Props come from
 *   useQuoteSidebarData (T-05).
 *
 * LINE LIMIT: ≤ 130 LOC (plan).
 */

// WHY no "use client": pure display — props only, no browser APIs.

import type { IntradayStatsResponse } from "@/types/api";
import { MetricCell } from "@/components/primitives/MetricCell";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Format a price value to 2dp. null/undefined → undefined (renders "—"). */
function fmt2(v: number | null | undefined): string | undefined {
  if (v === null || v === undefined) return undefined;
  return v.toFixed(2);
}

/** Format a percentage with sign. null/undefined → undefined. */
function fmtPct(v: number | null | undefined): string | undefined {
  if (v === null || v === undefined) return undefined;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/** Format a 0-100 index value (RSI, SI%). null/undefined → undefined. */
function fmtIndex(v: number | null | undefined): string | undefined {
  if (v === null || v === undefined) return undefined;
  return v.toFixed(1);
}

/** Color intent for RSI (overbought/oversold thresholds). */
function rsiColor(rsi: number | null | undefined): "positive" | "negative" | "warning" | "default" {
  if (rsi === null || rsi === undefined) return "default";
  if (rsi >= 70) return "negative"; // WHY negative: overbought is a risk signal
  if (rsi <= 30) return "positive"; // WHY positive: oversold = potential bounce
  if (rsi >= 60) return "warning";  // Approaching overbought
  return "default";
}

/** Color intent for GAP % (positive = gap up, negative = gap down). */
function gapColor(gap: number | null | undefined): "positive" | "negative" | "default" {
  if (gap === null || gap === undefined) return "default";
  if (gap > 0) return "positive";
  if (gap < 0) return "negative";
  return "default";
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface IntradayStatsBandProps {
  /** Raw response from GET /v1/fundamentals/{id}/intraday-stats. */
  data: IntradayStatsResponse | undefined;
  /** True while the query is loading — renders "—" placeholders. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IntradayStatsBand({ data, isLoading = false }: IntradayStatsBandProps) {
  // WHY local extraction (not inline): cleaner conditional formatting below.
  const vwap = data?.vwap ?? null;
  const atr = data?.atr_14 ?? null;
  const rsi = data?.rsi_14 ?? null;
  const gap = data?.gap_pct ?? null;
  const premHigh = data?.premarket_high ?? null;
  const premLow = data?.premarket_low ?? null;
  const si = data?.short_interest_pct ?? null;

  // WHY show PREM only when premarket data is available (Δ — §7.4):
  //   After-hours, premarket_high is null. Hiding the cell prevents a
  //   permanently empty "—" column that wastes horizontal space.
  const showPrem = premHigh !== null || premLow !== null;

  // Premarket range string: "142.50 / 139.20" (high / low).
  const premValue =
    premHigh !== null && premLow !== null
      ? `${premHigh.toFixed(2)} / ${premLow.toFixed(2)}`
      : premHigh != null
        ? premHigh.toFixed(2)
        : undefined;

  return (
    // WHY data-table-grid: F1 §16.3 opt-in — sets --row-h=20px and inner borders. (Δ4)
    <div
      data-table-grid
      className="border-b border-[hsl(var(--border-subtle))]"
      aria-label="Intraday statistics"
      role="row"
    >
      <div className="flex h-full">
        {/* ── VWAP ──────────────────────────────────────────────────────── */}
        <div className="min-w-0 flex-1">
          <MetricCell
            label="VWAP"
            value={isLoading ? undefined : fmt2(vwap)}
            color="default"
          />
        </div>

        {/* ── ATR(14) ───────────────────────────────────────────────────── */}
        <div className="min-w-0 flex-1">
          <MetricCell
            label="ATR 14"
            value={isLoading ? undefined : fmt2(atr)}
            color="default"
          />
        </div>

        {/* ── RSI(14) — color encodes overbought/oversold ────────────────── */}
        <div className="min-w-0 flex-1">
          <MetricCell
            label="RSI 14"
            value={isLoading ? undefined : fmtIndex(rsi)}
            color={isLoading ? "default" : rsiColor(rsi)}
          />
        </div>

        {/* ── GAP % — open vs prior close ───────────────────────────────── */}
        <div className="min-w-0 flex-1">
          <MetricCell
            label="GAP %"
            value={isLoading ? undefined : fmtPct(gap)}
            color={isLoading ? "default" : gapColor(gap)}
          />
        </div>

        {/* ── PREM high / low — hidden outside market pre-session (Δ §7.4) ─ */}
        {showPrem ? (
          <div className="min-w-0 flex-1">
            <MetricCell
              label="PREM"
              value={isLoading ? undefined : premValue}
              color="muted"
            />
          </div>
        ) : (
          // WHY spacer div: keeps the 5 remaining cells evenly distributed at
          // 1/5 of the strip width instead of collapsing to 1/6.
          null
        )}

        {/* ── SI % — short interest as percent of float ─────────────────── */}
        <div className="min-w-0 flex-1">
          <MetricCell
            label="SI %"
            value={isLoading ? undefined : fmtIndex(si)}
            color="default"
          />
        </div>
      </div>
    </div>
  );
}
