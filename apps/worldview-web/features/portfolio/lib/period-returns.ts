/**
 * features/portfolio/lib/period-returns.ts — PURE period-return math over the
 * flow-adjusted TWR series (2026-06-10 sprint, Wave 2 portfolio surface).
 *
 * WHY THIS EXISTS: the new Performance panel on the Holdings overview shows
 * "1D / 1W / 1M / 3M return vs SPY" comparison rows. Both sides of each row
 * must be computed over the SAME calendar window or the comparison is
 * meaningless. Centralizing the window-slicing in pure functions (instead of
 * inline component math) makes the date-cutoff rule explicit and
 * unit-testable against hand-computed fixtures.
 *
 * DESIGN RULES (same contract as risk-metrics.ts):
 *   - Every function is PURE — no fetching, no Date.now(), no globals.
 *   - Every return is `null` (never a fake number) when the series does not
 *     actually COVER the requested window. A 5-day-old portfolio has no
 *     honest "1M return" — we show "—", not the since-inception number
 *     mislabelled as 1M.
 *
 * WINDOW RULE: for a window of N days ending at the series' last date L,
 * the window-start observation is the LAST point dated ≤ (L − N days).
 * WHY "last ≤ cutoff" (not "first ≥ cutoff"): trading-day series have gaps
 * (weekends/holidays); the value that was in force AT the cutoff is the
 * last observation on or before it — same carry-forward convention as
 * alignBenchmarkToDates in risk-metrics.ts.
 *
 * TWR COMPOSITION: TWR points carry the CUMULATIVE flow-adjusted return
 * since window start (fraction). The return BETWEEN two points a→b is the
 * geometric link  (1 + twr_b) / (1 + twr_a) − 1  — NOT the naive
 * subtraction twr_b − twr_a, which would be wrong whenever twr_a ≠ 0.
 *
 * WHO USES IT: PerformancePeriodsPanel (Holdings overview) and its tests.
 */

import type { TwrPoint } from "@/types/api";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Canonical comparison windows for the Performance panel. */
export const PERIOD_WINDOWS = [
  { label: "1D", days: 1 },
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "3M", days: 91 },
] as const;

export type PeriodWindowLabel = (typeof PERIOD_WINDOWS)[number]["label"];

/** One comparison row: portfolio vs benchmark over the same window. */
export interface PeriodReturnRow {
  label: PeriodWindowLabel;
  /** Portfolio TWR over the window, as a fraction. null = window not covered. */
  portfolio: number | null;
  /** Benchmark price return over the same window. null = no benchmark data. */
  benchmark: number | null;
  /** Excess return (portfolio − benchmark) in fraction points; null when either side is null. */
  excess: number | null;
}

// ── Date helpers ──────────────────────────────────────────────────────────────

/**
 * isoDaysBefore — "YYYY-MM-DD" minus N days, in UTC.
 * WHY Date.UTC (not new Date(str)): bare-string Date parsing is
 * timezone-dependent in some engines; UTC construction makes the cutoff
 * deterministic regardless of the user's local timezone.
 */
export function isoDaysBefore(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = Date.UTC(y, (m ?? 1) - 1, d ?? 1) - days * 86_400_000;
  return new Date(t).toISOString().slice(0, 10);
}

/**
 * lastAtOrBefore — index of the last point dated ≤ cutoff, or −1.
 * Inputs MUST be ascending by date (ISO strings sort lexicographically =
 * chronologically — the same invariant risk-metrics.ts relies on).
 */
function lastAtOrBefore(dates: readonly string[], cutoff: string): number {
  let idx = -1;
  for (let i = 0; i < dates.length; i++) {
    if (dates[i] <= cutoff) idx = i;
    else break; // ascending — once past the cutoff, stop
  }
  return idx;
}

// ── Window returns ────────────────────────────────────────────────────────────

/**
 * windowReturnFromTwr — portfolio TWR over the trailing `windowDays` window.
 *
 * FORMULA: r = (1 + twr_last) / (1 + twr_start) − 1   (geometric link)
 *
 * Returns null when:
 *   - fewer than 2 points (no return derivable), or
 *   - no point exists at-or-before the cutoff (the series doesn't reach
 *     back far enough to honestly cover the window), or
 *   - the start factor (1 + twr_start) is ≤ 0 (degenerate −100% history —
 *     division would fabricate a number).
 */
export function windowReturnFromTwr(
  points: readonly TwrPoint[],
  windowDays: number,
): number | null {
  if (points.length < 2) return null;
  const last = points[points.length - 1];
  const cutoff = isoDaysBefore(last.date, windowDays);
  const startIdx = lastAtOrBefore(
    points.map((p) => p.date),
    cutoff,
  );
  if (startIdx < 0) return null; // window not covered by the series
  const startFactor = 1 + points[startIdx].twr_cum;
  if (!(startFactor > 0) || !Number.isFinite(startFactor)) return null;
  return (1 + last.twr_cum) / startFactor - 1;
}

/**
 * windowReturnFromCloses — benchmark price return over the same window rule.
 *
 * FORMULA: r = close_last / close_start − 1
 *
 * Same null contract as windowReturnFromTwr (insufficient data / window not
 * covered / non-positive start close).
 */
export function windowReturnFromCloses(
  closes: readonly DatedValue[],
  windowDays: number,
): number | null {
  if (closes.length < 2) return null;
  const last = closes[closes.length - 1];
  const cutoff = isoDaysBefore(last.date, windowDays);
  const startIdx = lastAtOrBefore(
    closes.map((c) => c.date),
    cutoff,
  );
  if (startIdx < 0) return null;
  const start = closes[startIdx].value;
  if (!(start > 0) || !Number.isFinite(start)) return null;
  return last.value / start - 1;
}

// ── Comparison rows ───────────────────────────────────────────────────────────

/**
 * computePeriodReturns — the four "portfolio vs SPY" comparison rows.
 *
 * @param twrPoints  flow-adjusted TWR series (ascending; fraction units)
 * @param spyCloses  SPY daily closes (ascending). undefined/empty → every
 *                   benchmark column renders null ("—") with the panel's
 *                   "benchmark unavailable" caption — never a fake number.
 *
 * Each side is computed INDEPENDENTLY over its own series with the same
 * calendar-window rule, so a missing benchmark never suppresses the
 * portfolio number (and vice versa). `excess` requires both.
 */
export function computePeriodReturns(
  twrPoints: readonly TwrPoint[],
  spyCloses?: readonly DatedValue[],
): PeriodReturnRow[] {
  return PERIOD_WINDOWS.map(({ label, days }) => {
    const portfolio = windowReturnFromTwr(twrPoints, days);
    const benchmark =
      spyCloses && spyCloses.length > 0
        ? windowReturnFromCloses(spyCloses, days)
        : null;
    return {
      label,
      portfolio,
      benchmark,
      excess:
        portfolio != null && benchmark != null ? portfolio - benchmark : null,
    };
  });
}
