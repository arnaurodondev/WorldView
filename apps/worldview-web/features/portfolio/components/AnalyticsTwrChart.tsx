/**
 * features/portfolio/components/AnalyticsTwrChart.tsx — cumulative-return
 * ("TWR") chart with optional SPY / QQQ benchmark overlays (R2 sprint).
 *
 * WHY THIS REPLACES the old inline PerformanceChart in AnalyticsTab: the
 * old chart plotted raw $ NAV, which cannot be compared against a
 * benchmark (a $50k portfolio vs a $560 SPY price share no axis). This
 * chart rebases EVERY series — portfolio and benchmarks — to 0% at the
 * period start, so the vertical gap between lines at any date IS the
 * period-to-date excess return. The $ NAV view still exists in the
 * Holdings tab's PerformanceChartPanel, so nothing is lost.
 *
 * TWR CAVEAT (documented honestly — this is the user's money): S1's
 * value-history series is daily NAV without external cash-flow markers,
 * so the "TWR" here is V_t/V_0 − 1. That equals true time-weighted return
 * ONLY when no deposits/withdrawals occurred inside the window; with
 * flows it includes their effect. A flow-adjusted TWR needs a backend
 * series endpoint (flagged as a backend gap). The chart label says
 * "CUM. RETURN" rather than over-claiming "TWR".
 *
 * MATH: cumulativeReturnSeries / alignBenchmarkToDates /
 * benchmarkCumulativeReturns — all pure + unit-tested in
 * features/portfolio/lib/risk-metrics.ts (formulas documented there).
 *
 * DATA:
 *   - portfolio: GET /v1/portfolios/{id}/value-history (cache shared with
 *     DrawdownChart and the risk panel via the same query key).
 *   - benchmarks: useBenchmarkSeries (SPY/QQQ daily closes; cache shared
 *     with the client risk panel's beta computation).
 *
 * WHO USES IT: AnalyticsTab.
 */

"use client";
// WHY "use client": useQuery + recharts SVG rendering need a browser DOM.

import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import {
  cumulativeReturnSeries,
  alignBenchmarkToDates,
  benchmarkCumulativeReturns,
  type DatedValue,
} from "@/features/portfolio/lib/risk-metrics";

// ── Series colors ─────────────────────────────────────────────────────────────
// Terminal Dark chart tokens. WHY these three:
//   portfolio — primary (the hero line, always drawn first/brightest)
//   SPY       — chart-neutral grey (matches PerformanceChartPanel's muted
//               SPY treatment: the benchmark must not compete with the book)
//   QQQ       — chart-ma-slow blue (distinct from both; NOT green/red which
//               are reserved for P&L direction)
const COLOR_PORTFOLIO = "hsl(var(--primary))";
const COLOR_SPY = "hsl(var(--chart-neutral))";
const COLOR_QQQ = "hsl(var(--chart-ma-slow))";

// ── Props / types ─────────────────────────────────────────────────────────────

export interface AnalyticsTwrChartProps {
  portfolioId: string;
  /** Active period label — used only for the query key / aria label. */
  period: string;
  /** Days for the value-history fetch; undefined = full history ("ALL"). */
  periodDays?: number;
  /** Which benchmark overlays are toggled on. */
  benchmarks: { SPY: boolean; QQQ: boolean };
  /**
   * Benchmark closes from useBenchmarkSeries (lifted to AnalyticsTab so the
   * risk panel shares the same data). ticker → ascending daily closes.
   */
  benchmarkCloses: Record<string, DatedValue[]>;
}

/** One merged chart row. Benchmark fields are null where data is missing. */
interface ChartRow {
  date: string;
  portfolio: number;
  spy: number | null;
  qqq: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** "+4.21%" / "-1.30%" with sign — fraction in, display string out. */
function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const pct = (v * 100).toFixed(2);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

/**
 * buildChartRows — merge the portfolio cumulative-return series with the
 * rebased benchmark overlays on the PORTFOLIO's date grid.
 *
 * WHY the portfolio grid is the master axis: the chart exists to explain
 * the portfolio; benchmarks are annotations. Mapping benchmarks onto the
 * portfolio dates (carry-forward, see alignBenchmarkToDates) guarantees
 * every drawn portfolio point has a directly-comparable benchmark value.
 *
 * Exported for unit tests (benchmark-normalization wiring).
 */
export function buildChartRows(
  portfolioPoints: DatedValue[],
  benchmarks: { SPY: boolean; QQQ: boolean },
  closesByTicker: Record<string, DatedValue[]>,
): ChartRow[] {
  const portfolioCum = cumulativeReturnSeries(portfolioPoints);
  if (portfolioCum.length === 0) return [];

  const dates = portfolioCum.map((p) => p.date);

  /** Rebased benchmark series for one ticker (null where unavailable). */
  const overlayFor = (ticker: "SPY" | "QQQ"): Array<number | null> => {
    const closes = closesByTicker[ticker];
    if (!benchmarks[ticker] || !closes || closes.length === 0) {
      return dates.map(() => null);
    }
    // Align closes to portfolio dates, then rebase to 0% at the first
    // matched close — the same "start at 0%" normalization the portfolio
    // series gets, which is what makes the lines comparable.
    return benchmarkCumulativeReturns(alignBenchmarkToDates(dates, closes));
  };

  const spy = overlayFor("SPY");
  const qqq = overlayFor("QQQ");

  return portfolioCum.map((p, i) => ({
    date: p.date,
    portfolio: p.ret,
    spy: spy[i],
    qqq: qqq[i],
  }));
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsTwrChart({
  portfolioId,
  period,
  periodDays,
  benchmarks,
  benchmarkCloses,
}: AnalyticsTwrChartProps) {
  const apiClient = useApiClient();

  // Same query key as DrawdownChart / risk panel → one fetch, three readers.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        // "ALL" omits days — server returns full history (matches the
        // AnalyticsPeriodReturnsTable convention).
        ...(periodDays != null ? { days: periodDays } : {}),
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  if (isLoading) {
    return <Skeleton className="h-[180px] w-full" data-testid="twr-chart-skeleton" />;
  }

  if (isError || !data) {
    return (
      <div className="h-[180px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-negative font-mono">
          Couldn&apos;t load return series.
        </p>
      </div>
    );
  }

  const points: DatedValue[] = (data.points ?? []).map((p) => ({
    date: p.date,
    value: p.value,
  }));
  const rows = buildChartRows(points, benchmarks, benchmarkCloses);

  if (rows.length === 0) {
    // Named empty state — value-history needs snapshots before a return
    // series exists. NEVER draw a fabricated flat line.
    return (
      <div
        data-testid="twr-chart-empty"
        className="h-[180px] flex items-center justify-center border border-border rounded-[2px]"
      >
        <p className="text-[11px] text-muted-foreground font-mono">
          Not enough data — returns appear after ~2 daily snapshots.
        </p>
      </div>
    );
  }

  // ── Custom tooltip: every visible series with its color + signed % ──────
  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ value: number; dataKey: string; stroke: string }>;
    label?: string;
  }) => {
    if (!active || !payload?.length) return null;
    const nameFor: Record<string, string> = {
      portfolio: "Portfolio",
      spy: "SPY",
      qqq: "QQQ",
    };
    return (
      <div className="bg-card border border-border rounded-[2px] px-2 py-1.5">
        <p className="text-[10px] text-muted-foreground">{label}</p>
        {payload.map((entry) => (
          <p
            key={entry.dataKey}
            className="text-[11px] font-mono tabular-nums"
            style={{ color: entry.stroke }}
          >
            {nameFor[entry.dataKey] ?? entry.dataKey} {fmtPct(entry.value)}
          </p>
        ))}
      </div>
    );
  };

  return (
    <div
      role="img"
      aria-label={`Portfolio cumulative return for ${period} period${benchmarks.SPY ? " with SPY overlay" : ""}${benchmarks.QQQ ? " with QQQ overlay" : ""}`}
      className="h-[180px] border border-border rounded-[2px]"
      data-testid="twr-chart"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
            tickLine={false}
            axisLine={false}
            // ≤5 x-ticks (design spec §4.3) — same density as the old chart.
            interval={Math.max(0, Math.floor(rows.length / 5) - 1)}
            // "YYYY-MM-DD" → "MM-DD" for compact tick labels.
            tickFormatter={(v: string) => (typeof v === "string" ? v.slice(5) : v)}
          />
          <YAxis
            tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
            tickLine={false}
            axisLine={false}
            width={44}
            // Fractions → "+5%" axis labels (signed, 0 decimals — axis is
            // for magnitude scanning; the tooltip has the precise value).
            tickFormatter={(v: number) =>
              `${v > 0 ? "+" : ""}${(v * 100).toFixed(0)}%`
            }
          />
          <Tooltip content={<CustomTooltip />} />
          {/* 0% line — the rebase baseline every series starts from. */}
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />

          {/* Benchmarks first so the portfolio line draws ON TOP of them. */}
          {benchmarks.SPY && (
            <Line
              type="monotone"
              dataKey="spy"
              stroke={COLOR_SPY}
              strokeWidth={1}
              strokeDasharray="4 2" // dashed = benchmark convention (matches PerformanceChartPanel)
              dot={false}
              // connectNulls bridges leading nulls (dates before the first
              // available close) — the line simply starts later.
              connectNulls
            />
          )}
          {benchmarks.QQQ && (
            <Line
              type="monotone"
              dataKey="qqq"
              stroke={COLOR_QQQ}
              strokeWidth={1}
              strokeDasharray="4 2"
              dot={false}
              connectNulls
            />
          )}

          {/* Portfolio — the hero line: solid, brightest, thickest. */}
          <Line
            type="monotone"
            dataKey="portfolio"
            stroke={COLOR_PORTFOLIO}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
