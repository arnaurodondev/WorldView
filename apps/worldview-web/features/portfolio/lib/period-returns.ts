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
  /**
   * True when the portfolio value was SUPPRESSED because the window contains
   * a flow artifact in the backend TWR series (see findFlowArtifactDates).
   * The panel renders "—" with an explanatory tooltip — never the corrupted
   * number. Distinct from `portfolio === null` due to coverage gaps, which
   * gets the generic "window not covered" treatment.
   */
  portfolioFlowArtifact: boolean;
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

// ── Flow-artifact detection (2026-06-11 Wave 3) ──────────────────────────────
//
// LIVE FINDING (portfolio 01900000-…-0100, /twr?days=95, 2026-06-11): the
// backend series is NOT reliably flow-adjusted. Hand-audited offending points:
//
//   2026-05-04  twrΔ +33.23%  while NAV moved +1.09%   (phantom flow applied)
//   2026-05-11  twrΔ +116.07% == navΔ +116.07%         (funding day counted as return)
//   2026-06-01  twrΔ +1.11%   while NAV frozen (Δ=0)   (flow on stale snapshots)
//   2026-06-08  twrΔ −2.09%   while NAV frozen (Δ=0)   (flow on stale snapshots)
//   2026-06-10  twrΔ +23.97%  == navΔ +23.97%          (flow/import counted as return)
//
// These artifacts made the Performance panel show 1D +23.97% / 3M +278.64%.
// The frontend window math was verified correct — the SERIES is wrong. Per
// the honesty contract we never "correct" backend numbers client-side; we
// DETECT windows that contain an artifact and render "—" with an explanatory
// tooltip until the backend series is fixed (S1 compute_twr.py: brokerage
// position imports change the NAV perimeter without a same-dated flow
// transaction, and snapshots can freeze while flows keep arriving).
//
// DETECTION RULES (deliberately narrow, to avoid suppressing honest data):
//   1. |interval TWR| > MAX_PLAUSIBLE_INTERVAL_TWR (15%): a flow-ADJUSTED
//      return of >15% between adjacent daily points is implausible for a
//      portfolio; every live artifact ≥ +23.97% trips this. A correctly
//      adjusted deposit does NOT trip it (its twrΔ stays small even when
//      navΔ is huge), so legitimate flow days are not suppressed.
//   2. NAV exactly frozen (navΔ === 0) while the TWR moved: a return with
//      zero value change means a flow was applied against stale snapshots.
//
// WHY NOT a twrΔ-vs-navΔ divergence rule: divergence is EXPECTED on every
// correctly handled flow day (navΔ includes the flow, twrΔ excludes it) —
// flagging it would suppress exactly the windows TWR exists to cover.

/**
 * Max plausible flow-adjusted return between two adjacent series points.
 * 15% is far above any realistic daily portfolio move (2026-06-10's −4.6%
 * book day was an outlier) yet far below the live artifacts (+23.97%/+116%).
 */
export const MAX_PLAUSIBLE_INTERVAL_TWR = 0.15;

/**
 * Rule 1 only applies to SHORT intervals (≤5 calendar days — tolerant of a
 * weekend + holiday gap). A sparse series can legitimately compress weeks of
 * market move into one long interval (e.g. a 2-point 30-day window returning
 * +20%), where a 15% bound would be a false positive. Every live artifact
 * sits on a 1–3 day interval. Frozen-NAV detection (rule 2) is span-agnostic.
 */
export const MAX_ARTIFACT_INTERVAL_DAYS = 5;

/** Calendar-day span between two ISO dates (UTC, deterministic). */
function isoDaySpan(fromIso: string, toIso: string): number {
  const [fy, fm, fd] = fromIso.split("-").map(Number);
  const [ty, tm, td] = toIso.split("-").map(Number);
  return Math.round(
    (Date.UTC(ty, (tm ?? 1) - 1, td ?? 1) - Date.UTC(fy, (fm ?? 1) - 1, fd ?? 1)) / 86_400_000,
  );
}

/**
 * Tolerance for "the TWR moved" against a frozen NAV. 1bp absorbs the
 * backend's 6-decimal percent rounding; real frozen-NAV artifacts in the
 * live series are 110×–209× larger (+1.11% / −2.09%).
 */
export const FROZEN_NAV_TWR_EPS = 0.0001;

/**
 * findFlowArtifactDates — END dates of intervals where the TWR series shows
 * a cash-flow artifact (see rules above). Pure; exported for the Analytics
 * chart's warning chip and for tests.
 */
export function findFlowArtifactDates(points: readonly TwrPoint[]): string[] {
  const out: string[] = [];
  for (let i = 1; i < points.length; i++) {
    if (isFlowArtifactInterval(points[i - 1], points[i])) out.push(points[i].date);
  }
  return out;
}

/** One-interval artifact test (rules 1 + 2 above). */
export function isFlowArtifactInterval(prev: TwrPoint, curr: TwrPoint): boolean {
  const prevFactor = 1 + prev.twr_cum;
  // Degenerate −100% base — windowReturnFromTwr already nulls these windows;
  // the interval itself cannot be classified, so don't flag it here.
  if (!(prevFactor > 0) || !Number.isFinite(prevFactor)) return false;
  const twrDelta = (1 + curr.twr_cum) / prevFactor - 1;

  // Rule 1: implausibly large flow-adjusted return over a SHORT interval.
  // Long sparse intervals (e.g. a 2-point 30-day window) can honestly carry
  // large moves — only daily-scale jumps are artifact signatures.
  if (
    Math.abs(twrDelta) > MAX_PLAUSIBLE_INTERVAL_TWR &&
    isoDaySpan(prev.date, curr.date) <= MAX_ARTIFACT_INTERVAL_DAYS
  ) {
    return true;
  }

  // Rule 2: TWR moved while NAV is exactly frozen (stale-snapshot flow).
  // Exact equality is intentional — frozen snapshots repeat the identical
  // 8-dp Decimal, while genuine market closes essentially never do.
  if (prev.nav === curr.nav && prev.nav > 0 && Math.abs(twrDelta) > FROZEN_NAV_TWR_EPS) {
    return true;
  }
  return false;
}

/** Result of a guarded window computation (value XOR artifact-suppression). */
export interface GuardedWindowReturn {
  /** Window TWR fraction, or null (not covered OR artifact-suppressed). */
  value: number | null;
  /** True when the value was suppressed because the window contains an artifact. */
  flowArtifact: boolean;
}

/**
 * windowReturnFromTwrGuarded — windowReturnFromTwr + artifact suppression.
 *
 * When the window is covered but ANY interval inside it is a flow artifact,
 * the corrupted number is withheld ({ value: null, flowArtifact: true }) so
 * the UI can show "—" with an honest tooltip instead of "+278.64%".
 */
export function windowReturnFromTwrGuarded(
  points: readonly TwrPoint[],
  windowDays: number,
): GuardedWindowReturn {
  const value = windowReturnFromTwr(points, windowDays);
  if (value == null) return { value: null, flowArtifact: false };

  // Re-derive the window-start index with the same cutoff rule so the
  // artifact scan covers exactly the linked intervals (startIdx → last).
  const last = points[points.length - 1];
  const cutoff = isoDaysBefore(last.date, windowDays);
  const startIdx = lastAtOrBefore(
    points.map((p) => p.date),
    cutoff,
  );
  for (let i = startIdx + 1; i < points.length; i++) {
    if (isFlowArtifactInterval(points[i - 1], points[i])) {
      return { value: null, flowArtifact: true };
    }
  }
  return { value, flowArtifact: false };
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
    // 2026-06-11 Wave 3: the GUARDED variant — windows containing a backend
    // flow artifact (deposit counted as return, see findFlowArtifactDates)
    // are suppressed to null + flagged instead of showing "+278.64%".
    const { value: portfolio, flowArtifact } = windowReturnFromTwrGuarded(
      twrPoints,
      days,
    );
    const benchmark =
      spyCloses && spyCloses.length > 0
        ? windowReturnFromCloses(spyCloses, days)
        : null;
    return {
      label,
      portfolio,
      portfolioFlowArtifact: flowArtifact,
      benchmark,
      excess:
        portfolio != null && benchmark != null ? portfolio - benchmark : null,
    };
  });
}
