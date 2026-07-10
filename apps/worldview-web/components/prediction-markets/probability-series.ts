/**
 * components/prediction-markets/probability-series.ts — pure transforms for the
 * ProbabilityChart (PLAN-0056 Wave E2).
 *
 * WHY a SEPARATE pure module (no React, no recharts): pivoting the S3 per-token
 * price points into chart rows and computing the YES Δ are pure functions of the
 * data. Keeping them out of the component lets us unit-test the maths directly
 * (no DOM, no mount) AND lets the detail Sheet reuse computeYesDeltaPp for the
 * SignalBadge without importing the chart.
 */

import type { PredictionMarketPricePoint } from "@/types/api";

/** One recharts row: a timestamp plus one implied-% value per outcome series. */
export interface ProbabilityChartRow {
  /** ISO timestamp (x-axis key). */
  ts: string;
  /** Short x-axis tick label derived from ts. */
  label: string;
  /** outcomeKey → implied probability in PERCENT (0–100). */
  [series: string]: string | number | null;
}

/**
 * seriesKey — stable key/label for an outcome. Prefer the human name
 * ("Yes"/"No"); fall back to a short token id when the feed omitted the name.
 */
export function seriesKey(point: PredictionMarketPricePoint): string {
  if (point.outcome_name && point.outcome_name.trim().length > 0) {
    return point.outcome_name.trim();
  }
  // WHY slice: raw token ids are long hashes — a 6-char prefix keeps the legend
  // readable while staying unique enough within a single market's 2–4 outcomes.
  return `#${point.token_id.slice(0, 6)}`;
}

/**
 * pivotPricePoints — turn the flat per-token point list into wide chart rows.
 *
 * S3 returns one row PER outcome token PER time bucket. recharts wants one row
 * per timestamp with a column per series. We group by `window_start_ts`, and for
 * each row set `row[seriesKey] = price * 100` (implied % for a [0,100] axis).
 *
 * Returns { rows, series } where `series` is the ordered list of distinct
 * outcome keys (so the caller can render one <Line> per series with a stable
 * colour assignment).
 */
export function pivotPricePoints(points: PredictionMarketPricePoint[]): {
  rows: ProbabilityChartRow[];
  series: string[];
} {
  const byTs = new Map<string, ProbabilityChartRow>();
  const series: string[] = [];

  // Sort ascending by time so the line moves left→right chronologically.
  const sorted = [...points].sort(
    (a, b) => new Date(a.window_start_ts).getTime() - new Date(b.window_start_ts).getTime(),
  );

  for (const p of sorted) {
    const key = seriesKey(p);
    if (!series.includes(key)) series.push(key);

    let row = byTs.get(p.window_start_ts);
    if (!row) {
      row = { ts: p.window_start_ts, label: formatTick(p.window_start_ts) };
      byTs.set(p.window_start_ts, row);
    }
    // Clamp to [0,100] — implied probabilities should already be in [0,1] but a
    // bad feed value shouldn't blow out the axis.
    row[key] = Math.max(0, Math.min(100, p.price * 100));
  }

  return { rows: Array.from(byTs.values()), series };
}

/**
 * computeYesDeltaPp — YES-probability change (percentage points) across the
 * series, first→last bucket. Used by the SignalBadge "moving" driver.
 *
 * WHY YES-only: the badge is a single directional cue. We locate the "Yes"
 * outcome (case-insensitive); if a market has no YES outcome (multi-outcome),
 * we return null and the badge simply shows no move — honest rather than
 * picking an arbitrary outcome.
 *
 * Returns null when there are fewer than 2 YES points (no measurable move).
 */
export function computeYesDeltaPp(points: PredictionMarketPricePoint[]): number | null {
  const yes = points
    .filter((p) => (p.outcome_name ?? "").toLowerCase() === "yes")
    .sort(
      (a, b) => new Date(a.window_start_ts).getTime() - new Date(b.window_start_ts).getTime(),
    );
  if (yes.length < 2) return null;
  const first = yes[0].price * 100;
  const last = yes[yes.length - 1].price * 100;
  return last - first;
}

/**
 * formatTick — compact x-axis label. "Jul 3" for day/week bars, "14:00" feel is
 * avoided (bars are UTC bucket starts); month+day reads cleanly at every zoom.
 */
export function formatTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(d);
}
