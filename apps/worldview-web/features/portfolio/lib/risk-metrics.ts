/**
 * features/portfolio/lib/risk-metrics.ts — PURE portfolio risk/return math.
 *
 * WHY THIS EXISTS (R2 enhancement sprint): the Analytics surface needs
 * client-side risk metrics (Sharpe, max drawdown, annualized volatility,
 * beta vs SPY) and benchmark-overlay normalization that are PERIOD-ALIGNED
 * with the TWR chart. The S9 `/risk-metrics` endpoint computes similar
 * figures but over its own `lookback_days` window — having the math here
 * guarantees the risk panel describes EXACTLY the series the user is
 * looking at on the chart, point for point.
 *
 * DESIGN RULES:
 *   - Every function is PURE (no fetching, no Date.now(), no globals) so it
 *     is trivially unit-testable against hand-computed fixtures.
 *   - Every metric returns `null` (never a fake number) when the input is
 *     insufficient or degenerate. This is the user's money — an honest "—"
 *     beats a fabricated statistic (Round-2 brief: correctness over
 *     completeness).
 *   - All formulas are documented inline so a reviewer can verify the math
 *     without leaving the file.
 *
 * DATA MODEL: the portfolio series comes from S1 value-history (daily NAV
 * snapshots). NOTE / KNOWN LIMITATION: S1 does not expose external cash
 * flows (deposits/withdrawals), so the "TWR" computed here is a simple
 * NAV-relative cumulative return — it is exact when there are no external
 * flows in the window and overstates/understates performance when there
 * are. A flow-adjusted TWR requires a backend series endpoint (flagged as
 * a backend gap in the R2 report).
 *
 * WHO USES IT: AnalyticsTwrChart, AnalyticsRiskMetricsPanel, DrawdownChart
 * (via AnalyticsTab), and their tests.
 */

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * MIN_OBSERVATIONS — minimum number of DAILY RETURN observations required
 * before any statistical metric (Sharpe / volatility / beta / max drawdown)
 * is reported.
 *
 * WHY 20: with fewer than ~20 daily returns (≈ one trading month) the
 * sample standard deviation is so noisy that an annualized Sharpe can swing
 * from -3 to +3 on a single data point. Showing such a number would be
 * actively misleading. 20 comes from the Round-2 brief ("em-dash +
 * 'insufficient data' tooltip when series < 20 observations").
 */
export const MIN_OBSERVATIONS = 20;

/**
 * TRADING_DAYS_PER_YEAR — annualization factor base.
 *
 * WHY 252: US equity markets trade ~252 days/year (365 − weekends −
 * holidays). Volatility scales with √t, so daily stdev × √252 = annual
 * stdev. This is the universal convention (used by S9's risk-metrics
 * endpoint too, keeping the two panels comparable).
 */
export const TRADING_DAYS_PER_YEAR = 252;

/**
 * Degenerate-variance guards. WHY epsilons (not `=== 0`): a CONSTANT
 * return series should have variance exactly 0, but float accumulation
 * leaves residues around 1e-36 (e.g. mean(Array(20).fill(0.01)) ≠ 0.01 in
 * the last bit). Dividing by that residue produces a confidently-wrong
 * Sharpe/beta instead of an honest null. Thresholds are chosen far below
 * any REAL market figure: a genuine daily stdev of 1e-5 (0.001%/day, i.e.
 * essentially cash) is still 10,000× above EPS_STDEV.
 */
const EPS_STDEV = 1e-9;
const EPS_VARIANCE = 1e-18; // = EPS_STDEV²

// ── Types ─────────────────────────────────────────────────────────────────────

/** One (date, value) observation — date is "YYYY-MM-DD". */
export interface DatedValue {
  date: string;
  value: number;
}

/** One point on a cumulative-return ("TWR") series. `ret` is a 0-based fraction (0.05 = +5%). */
export interface CumulativeReturnPoint {
  date: string;
  /** Cumulative return since the first point of the window: V_t / V_0 − 1. */
  ret: number;
}

/** One point on a drawdown series. `drawdown` is ≤ 0 (e.g. -0.12 = 12% below peak). */
export interface DrawdownPoint {
  date: string;
  drawdown: number;
}

/** Bundle returned by computeRiskMetrics — every field independently nullable. */
export interface ClientRiskMetrics {
  /** Annualized Sharpe ratio, rf = 0 (see annualizedSharpe). */
  sharpe: number | null;
  /** Annualized volatility as a fraction (0.18 = 18%/yr). */
  volatilityAnnualized: number | null;
  /** Max peak-to-trough drawdown over the window, ≤ 0 fraction. */
  maxDrawdown: number | null;
  /** Beta vs the supplied benchmark return series (null when no benchmark). */
  beta: number | null;
  /** Number of daily-return observations the metrics were computed from. */
  nObservations: number;
}

// ── Basic statistics (internal helpers, exported for testability) ────────────

/** Arithmetic mean. Returns null for an empty array (never NaN). */
export function mean(xs: readonly number[]): number | null {
  if (xs.length === 0) return null;
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

/**
 * sampleStdDev — sample standard deviation (n−1 denominator, Bessel's
 * correction).
 *
 * WHY n−1 (not n): the return series is a SAMPLE of the return-generating
 * process, not the full population. Bessel's correction removes the bias
 * in the variance estimate; it is the convention used by every risk
 * platform (and by numpy's `ddof=1`).
 *
 * Returns null when fewer than 2 observations (variance undefined).
 */
export function sampleStdDev(xs: readonly number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs)!;
  const ssq = xs.reduce((s, x) => s + (x - m) * (x - m), 0);
  return Math.sqrt(ssq / (xs.length - 1));
}

// ── Return-series construction ────────────────────────────────────────────────

/**
 * dailyReturns — simple (arithmetic) daily returns from a value series.
 *
 * FORMULA: r_t = V_t / V_{t−1} − 1
 *
 * WHY simple (not log) returns: Sharpe/vol/beta conventions in brokerage
 * UIs (IBKR Portfolio Analyst, Bloomberg PORT) use arithmetic daily
 * returns; the S9 risk-metrics endpoint does the same, keeping the two
 * panels comparable.
 *
 * EDGE CASE — non-positive denominators: a snapshot with V_{t−1} ≤ 0
 * (empty portfolio / data wipe artifact, see F-209 "data_anomaly") makes
 * the ratio meaningless. Those pairs are SKIPPED rather than emitted as
 * ±Infinity, which would destroy every downstream statistic.
 */
export function dailyReturns(values: readonly number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < values.length; i++) {
    const prev = values[i - 1];
    const curr = values[i];
    // Skip pairs where the base is non-positive (division by ≤0 is
    // meaningless) or either value is non-finite (defensive against NaN
    // leaking in from a parse failure upstream).
    if (prev > 0 && Number.isFinite(prev) && Number.isFinite(curr)) {
      out.push(curr / prev - 1);
    }
  }
  return out;
}

/**
 * cumulativeReturnSeries — normalize a NAV/price series to cumulative
 * return since the FIRST point of the window ("rebase to 0%").
 *
 * FORMULA: ret_t = V_t / V_0 − 1
 *
 * WHY rebase to 0%: this is what makes a portfolio line and a benchmark
 * line COMPARABLE on one axis — both start at exactly 0% at period start,
 * so the vertical gap between them at any date is the period-to-date
 * excess return (alpha). Plotting raw $ NAV vs raw $ SPY price would be
 * meaningless (different magnitudes).
 *
 * Points with a non-positive first value yield an empty series (cannot
 * rebase against a 0/negative base — would fabricate returns).
 */
export function cumulativeReturnSeries(
  points: readonly DatedValue[],
): CumulativeReturnPoint[] {
  if (points.length === 0) return [];
  const base = points[0].value;
  if (!(base > 0) || !Number.isFinite(base)) return [];
  return points.map((p) => ({ date: p.date, ret: p.value / base - 1 }));
}

/**
 * drawdownSeries — underwater curve from a value series.
 *
 * FORMULA: dd_t = V_t / max(V_0..V_t) − 1   (running-peak relative)
 *
 * Always ≤ 0; equals 0 whenever the series is at a new high. This is the
 * exact formula from the Round-2 brief ("dd_t = V_t/max(V_0..t) - 1").
 * Peaks with value ≤ 0 produce dd = 0 (avoid division by zero — an empty
 * portfolio has no meaningful drawdown).
 */
export function drawdownSeries(points: readonly DatedValue[]): DrawdownPoint[] {
  if (points.length === 0) return [];
  let peak = points[0].value;
  return points.map((p) => {
    if (p.value > peak) peak = p.value;
    return { date: p.date, drawdown: peak > 0 ? p.value / peak - 1 : 0 };
  });
}

// ── Risk metrics ──────────────────────────────────────────────────────────────

/**
 * maxDrawdown — deepest point of the drawdown series (most negative dd_t).
 *
 * Returns null when there are fewer than MIN_OBSERVATIONS daily returns
 * derivable from the series (i.e. < MIN_OBSERVATIONS + 1 points). WHY gate
 * max-drawdown on the same threshold as the statistical metrics: a 3-day
 * series trivially has ~0 drawdown, which would read as "this portfolio
 * never loses" — a misleading statement, not a neutral one.
 */
export function maxDrawdown(points: readonly DatedValue[]): number | null {
  if (points.length < MIN_OBSERVATIONS + 1) return null;
  const dds = drawdownSeries(points);
  if (dds.length === 0) return null;
  return dds.reduce((min, p) => Math.min(min, p.drawdown), 0);
}

/**
 * annualizedVolatility — sample stdev of daily returns scaled to annual.
 *
 * FORMULA: σ_ann = stdev(r_daily, n−1) × √252
 *
 * WHY √252: volatility grows with the square root of time under the i.i.d.
 * returns assumption (variance is additive across days ⇒ stdev scales by
 * √t). 252 trading days/year is the market convention.
 *
 * Returns null when fewer than MIN_OBSERVATIONS return observations.
 */
export function annualizedVolatility(
  returns: readonly number[],
): number | null {
  if (returns.length < MIN_OBSERVATIONS) return null;
  const sd = sampleStdDev(returns);
  if (sd == null) return null;
  return sd * Math.sqrt(TRADING_DAYS_PER_YEAR);
}

/**
 * annualizedSharpe — annualized Sharpe ratio with rf = 0.
 *
 * FORMULA: Sharpe = (mean(r_daily) / stdev(r_daily, n−1)) × √252
 *
 * WHY rf = 0 (ASSUMPTION, per the Round-2 brief): we have no risk-free
 * rate feed in the platform, and for the typical retail holding period the
 * daily T-bill accrual (~0.02%/day) is far smaller than daily equity noise.
 * The assumption is surfaced in the panel hint so the user knows the number
 * is an excess-return-over-zero Sharpe. When a rate feed lands, subtract
 * rf_daily from each return before averaging.
 *
 * WHY annualize via √252 on the RATIO: mean scales by 252, stdev by √252,
 * so the ratio scales by 252/√252 = √252.
 *
 * Returns null when:
 *   - fewer than MIN_OBSERVATIONS returns (statistically meaningless), or
 *   - stdev is ~0 (flat series — division by (near-)zero; a constant-value
 *     series has no defined Sharpe; see EPS_STDEV for the epsilon rationale).
 */
export function annualizedSharpe(returns: readonly number[]): number | null {
  if (returns.length < MIN_OBSERVATIONS) return null;
  const m = mean(returns);
  const sd = sampleStdDev(returns);
  if (m == null || sd == null || sd < EPS_STDEV) return null;
  return (m / sd) * Math.sqrt(TRADING_DAYS_PER_YEAR);
}

/**
 * betaVsBenchmark — CAPM beta of the portfolio vs a benchmark.
 *
 * FORMULA: β = cov(r_p, r_b) / var(r_b)
 *   cov(x, y) = Σ (x_i − x̄)(y_i − ȳ) / (n − 1)   (sample covariance)
 *   var(y)    = cov(y, y)
 *
 * INPUT CONTRACT: the two arrays MUST be index-aligned (same dates, same
 * length) — alignment is the CALLER's job (see alignBenchmarkToDates).
 * Mismatched lengths return null rather than silently truncating, because
 * a silent truncate would correlate Monday's portfolio move with Friday's
 * SPY move and produce a confidently wrong beta.
 *
 * Returns null when:
 *   - arrays differ in length or have < MIN_OBSERVATIONS pairs, or
 *   - benchmark variance is ~0 (β undefined — division by (near-)zero;
 *     see EPS_VARIANCE for why this is an epsilon, not `=== 0`).
 */
export function betaVsBenchmark(
  portfolioReturns: readonly number[],
  benchmarkReturns: readonly number[],
): number | null {
  const n = portfolioReturns.length;
  if (n !== benchmarkReturns.length) return null;
  if (n < MIN_OBSERVATIONS) return null;

  const mp = mean(portfolioReturns)!;
  const mb = mean(benchmarkReturns)!;

  let cov = 0;
  let varB = 0;
  for (let i = 0; i < n; i++) {
    const dp = portfolioReturns[i] - mp;
    const db = benchmarkReturns[i] - mb;
    cov += dp * db;
    varB += db * db;
  }
  // n−1 denominators cancel in the ratio, but compute them anyway for
  // clarity (and so cov/var are individually correct if ever extracted).
  cov /= n - 1;
  varB /= n - 1;

  if (varB < EPS_VARIANCE) return null;
  return cov / varB;
}

// ── Benchmark alignment ───────────────────────────────────────────────────────

/**
 * alignBenchmarkToDates — match benchmark closes onto the portfolio's date
 * grid using "last known close on or before the date" (carry-forward).
 *
 * WHY carry-forward (not exact-date join): S1 portfolio snapshots can land
 * on days the market was closed (weekend/holiday batch runs), and OHLCV
 * bars only exist for trading days. An exact-date join would drop those
 * snapshot points and silently shorten the series; carrying the last close
 * forward is the standard treatment (the benchmark genuinely had that
 * value on the non-trading day).
 *
 * RETURNS: array index-aligned with `dates`; null for dates BEFORE the
 * first available close (we never carry BACKWARD — that would fabricate
 * pre-history). Callers must handle leading nulls.
 *
 * COMPLEXITY: O(n + m) two-pointer sweep — both inputs are expected sorted
 * ascending by date ("YYYY-MM-DD" strings sort lexicographically, which is
 * exactly chronological for ISO dates — WHY string compare is safe here).
 */
export function alignBenchmarkToDates(
  dates: readonly string[],
  benchmarkCloses: readonly DatedValue[],
): Array<number | null> {
  const out: Array<number | null> = [];
  let j = 0;
  let lastClose: number | null = null;
  for (const date of dates) {
    // Advance the benchmark pointer to the last close ≤ this date.
    while (j < benchmarkCloses.length && benchmarkCloses[j].date <= date) {
      lastClose = benchmarkCloses[j].value;
      j++;
    }
    out.push(lastClose);
  }
  return out;
}

/**
 * benchmarkCumulativeReturns — rebase aligned benchmark closes to 0% at the
 * first NON-NULL observation.
 *
 * WHY rebase at first non-null (not index 0): when the benchmark has no
 * close before the portfolio's first date (e.g. a brand-new portfolio
 * whose first snapshot predates our OHLCV history), the leading entries
 * are null. Rebasing on the first real close keeps the overlay honest —
 * it starts where benchmark data genuinely starts instead of pretending.
 *
 * Output is index-aligned with the input; leading nulls are preserved so
 * the chart simply doesn't draw the benchmark there.
 */
export function benchmarkCumulativeReturns(
  alignedCloses: ReadonlyArray<number | null>,
): Array<number | null> {
  let base: number | null = null;
  return alignedCloses.map((close) => {
    if (close == null) return null;
    if (base == null) {
      if (!(close > 0)) return null; // cannot rebase on a ≤0 close
      base = close;
    }
    return close / base - 1;
  });
}

// ── Convenience bundle ────────────────────────────────────────────────────────

/**
 * computeRiskMetrics — one-call bundle for the risk panel.
 *
 * @param portfolioPoints  daily NAV series (the value-history points)
 * @param benchmarkCloses  daily benchmark closes for the SAME window
 *                         (unaligned — alignment happens inside). Pass
 *                         undefined to skip beta.
 *
 * Beta uses returns computed from the ALIGNED benchmark series so each
 * portfolio daily return is paired with the benchmark move over the same
 * calendar interval. Dates where the benchmark had no close yet are
 * dropped from BOTH series (pairwise-complete), preserving alignment.
 */
export function computeRiskMetrics(
  portfolioPoints: readonly DatedValue[],
  benchmarkCloses?: readonly DatedValue[],
): ClientRiskMetrics {
  const values = portfolioPoints.map((p) => p.value);
  const returns = dailyReturns(values);

  let beta: number | null = null;
  if (benchmarkCloses && benchmarkCloses.length > 0) {
    const aligned = alignBenchmarkToDates(
      portfolioPoints.map((p) => p.date),
      benchmarkCloses,
    );
    // Build PAIRED return arrays: for each consecutive portfolio-date pair
    // where both the portfolio AND the aligned benchmark have valid values,
    // emit one (r_p, r_b) pair. Pairs are dropped together so the arrays
    // stay index-aligned (betaVsBenchmark's hard requirement).
    const rp: number[] = [];
    const rb: number[] = [];
    for (let i = 1; i < portfolioPoints.length; i++) {
      const pv0 = portfolioPoints[i - 1].value;
      const pv1 = portfolioPoints[i].value;
      const bv0 = aligned[i - 1];
      const bv1 = aligned[i];
      if (pv0 > 0 && bv0 != null && bv0 > 0 && bv1 != null) {
        rp.push(pv1 / pv0 - 1);
        rb.push(bv1 / bv0 - 1);
      }
    }
    beta = betaVsBenchmark(rp, rb);
  }

  return {
    sharpe: annualizedSharpe(returns),
    volatilityAnnualized: annualizedVolatility(returns),
    maxDrawdown: maxDrawdown(portfolioPoints),
    beta,
    nObservations: returns.length,
  };
}
