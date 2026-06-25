/**
 * features/portfolio/components/AnalyticsTwrChart.tsx — flow-adjusted TWR
 * chart with optional SPY / QQQ benchmark overlays and an optional raw-NAV
 * return line. (R2 sprint; UPGRADED 2026-06-10 sprint gap #3.)
 *
 * WHAT CHANGED (2026-06-10): the portfolio line now comes from
 * GET /v1/portfolios/{id}/twr — S1 computes sub-period returns BETWEEN
 * external cash flows and geometrically links them, i.e. TRUE time-weighted
 * return. The previous implementation rebased the raw NAV series
 * (V_t/V_0 − 1), which counted every deposit/withdrawal as "performance"
 * and was honestly labelled "CUM. RETURN" to avoid over-claiming. The
 * header now says "TWR — FLOW-ADJUSTED" because that is finally what the
 * line IS; the old NAV-relative line survives as an opt-in overlay
 * ("NAV (unadj.)") so the user can see exactly how much of the raw NAV
 * move was flows — the vertical gap between the two lines.
 *
 * COMPARABILITY: every series — TWR, NAV-return, benchmarks — is rebased
 * to 0% at the window start (the TWR endpoint returns its first point at
 * exactly 0; VERIFIED LIVE 2026-06-11), so the vertical gap between any
 * two lines at any date is a real excess return.
 *
 * MATH: alignBenchmarkToDates / benchmarkCumulativeReturns /
 * cumulativeReturnSeries — pure + unit-tested in
 * features/portfolio/lib/risk-metrics.ts.
 *
 * DATA:
 *   - portfolio TWR + NAV: useTwrSeries (one fetch feeds both lines AND
 *     PerformancePeriodsPanel when windows coincide — shared qk key).
 *   - benchmarks: useBenchmarkSeries closes via props (lifted to
 *     AnalyticsTab so the risk panel shares the same data).
 *
 * WHO USES IT: AnalyticsTab (portfolio Analytics tab + /portfolio/analytics).
 */

"use client";
// WHY "use client": useQuery + recharts SVG rendering need a browser DOM.

// R4 hardening: useMemo — chart-row building ran in render on every parent
// re-render; see the rows memo below. useState drives the NAV toggle.
import { useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

// R3 polish: LineChartIcon categorises the "insufficient data" EmptyState.
import { LineChart as LineChartIcon } from "lucide-react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
// R3 polish (DS §15.12): shared EmptyState primitive for the named
// "insufficient analytics data" state (was a hand-rolled bordered div).
import { EmptyState } from "@/components/primitives/EmptyState";
import { useTwrSeries } from "@/features/portfolio/hooks/useTwrSeries";
// 2026-06-11 Wave 3: flow-artifact detection — the chart cannot suppress its
// line (the user needs to SEE the series), but it must NAME the corruption
// when the backend counted a deposit/position import as return (live audit:
// +116% on 2026-05-11, +23.97% on 2026-06-10 — both funding events).
import { findFlowArtifactDates } from "@/features/portfolio/lib/period-returns";
import {
  cumulativeReturnSeries,
  alignBenchmarkToDates,
  benchmarkCumulativeReturns,
  type DatedValue,
} from "@/features/portfolio/lib/risk-metrics";
import type { TwrPoint } from "@/types/api";

// ── Series colors ─────────────────────────────────────────────────────────────
// Terminal Dark chart tokens. WHY these:
//   portfolio — primary (the hero line, always drawn first/brightest)
//   NAV       — muted-foreground dotted (a caveat line, must read as secondary)
//   SPY       — chart-neutral grey (benchmark must not compete with the book)
//   QQQ       — chart-ma-slow blue (distinct; NOT green/red — P&L colors)
const COLOR_PORTFOLIO = "hsl(var(--primary))";
const COLOR_NAV = "hsl(var(--muted-foreground))";
const COLOR_SPY = "hsl(var(--chart-neutral))";
const COLOR_QQQ = "hsl(var(--chart-ma-slow))";

/**
 * "ALL" period → 3650 days. The TWR endpoint requires a concrete window
 * (1–3650); 10 years is its documented maximum. This is the one place the
 * chart's "ALL" differs from the value-history "ALL" (true full history) —
 * acceptable: no demo or realistic retail book predates a 10y window.
 */
const TWR_MAX_DAYS = 3650;

// ── Props / types ─────────────────────────────────────────────────────────────

export interface AnalyticsTwrChartProps {
  portfolioId: string;
  /** Active period label — used only for the query key / aria label. */
  period: string;
  /** Days for the TWR fetch; undefined = "ALL" → TWR_MAX_DAYS. */
  periodDays?: number;
  /** Which benchmark overlays are toggled on. */
  benchmarks: { SPY: boolean; QQQ: boolean };
  /**
   * Benchmark closes from useBenchmarkSeries (lifted to AnalyticsTab so the
   * risk panel shares the same data). ticker → ascending daily closes.
   */
  benchmarkCloses: Record<string, DatedValue[]>;
}

/** One merged chart row. Optional series are null where data is missing/off. */
interface ChartRow {
  date: string;
  portfolio: number;
  /** NAV-relative cumulative return (the pre-TWR approximation) — opt-in. */
  nav: number | null;
  spy: number | null;
  qqq: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** "+4.21%" / "-1.30%" with sign — fraction in, display string out.
 *  R3 polish: ZERO stays unsigned ("0.00%") — signedPrice convention (R1):
 *  a flat return has no direction, "+0.00%" would falsely imply a gain. */
function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const pct = (v * 100).toFixed(2);
  return v > 0 ? `+${pct}%` : `${pct}%`;
}

/**
 * buildChartRows — LEGACY NAV-path builder (kept exported: the R2 wiring
 * tests pin its rebase/alignment behaviour, and it remains the correct
 * primitive for any consumer that only has a raw value series).
 * Merges a raw NAV series (rebased client-side) with benchmark overlays.
 */
export function buildChartRows(
  portfolioPoints: DatedValue[],
  benchmarks: { SPY: boolean; QQQ: boolean },
  closesByTicker: Record<string, DatedValue[]>,
): Array<{ date: string; portfolio: number; spy: number | null; qqq: number | null }> {
  const portfolioCum = cumulativeReturnSeries(portfolioPoints);
  if (portfolioCum.length === 0) return [];

  const dates = portfolioCum.map((p) => p.date);

  /** Rebased benchmark series for one ticker (null where unavailable). */
  const overlayFor = (ticker: "SPY" | "QQQ"): Array<number | null> => {
    const closes = closesByTicker[ticker];
    if (!benchmarks[ticker] || !closes || closes.length === 0) {
      return dates.map(() => null);
    }
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

/**
 * buildTwrChartRows — merge the server TWR series with the optional
 * NAV-return line and the rebased benchmark overlays, all on the TWR
 * series' date grid.
 *
 * WHY the TWR grid is the master axis: the chart exists to explain the
 * portfolio; the NAV line and benchmarks are annotations. The TWR endpoint
 * already returns its first point at 0 (server-side rebase at window
 * start), so `twr_cum` is plotted as-is — re-rebasing client-side would
 * double-apply the normalization.
 *
 * NAV line: cumulativeReturnSeries over the SAME response's `nav` field —
 * the exact pre-sprint approximation (V_t/V_0 − 1), so the TWR↔NAV gap is
 * the flows' contribution. null on every row when `showNav` is off.
 *
 * Exported for unit tests (TWR wiring + NAV toggle).
 */
export function buildTwrChartRows(
  twrPoints: readonly TwrPoint[],
  showNav: boolean,
  benchmarks: { SPY: boolean; QQQ: boolean },
  closesByTicker: Record<string, DatedValue[]>,
): ChartRow[] {
  if (twrPoints.length === 0) return [];

  const dates = twrPoints.map((p) => p.date);

  // NAV-relative cumulative return on the same grid (legacy approximation).
  // cumulativeReturnSeries returns [] for an un-rebasable series (first
  // NAV ≤ 0) — the navAt lookup then yields null for every row: honest "no
  // line" instead of a fabricated flat one.
  const navCum = showNav
    ? cumulativeReturnSeries(twrPoints.map((p) => ({ date: p.date, value: p.nav })))
    : [];
  const navByDate = new Map(navCum.map((p) => [p.date, p.ret]));

  const overlayFor = (ticker: "SPY" | "QQQ"): Array<number | null> => {
    const closes = closesByTicker[ticker];
    if (!benchmarks[ticker] || !closes || closes.length === 0) {
      return dates.map(() => null);
    }
    // Align closes to the TWR dates, then rebase to 0% at the first matched
    // close — the same "start at 0%" normalization the TWR series has.
    return benchmarkCumulativeReturns(alignBenchmarkToDates(dates, closes));
  };

  const spy = overlayFor("SPY");
  const qqq = overlayFor("QQQ");

  return twrPoints.map((p, i) => ({
    date: p.date,
    portfolio: p.twr_cum,
    nav: showNav ? (navByDate.get(p.date) ?? null) : null,
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
  // ── NAV overlay toggle — default OFF (the TWR line is the headline; the
  // unadjusted NAV return is a diagnostic the user opts into). Local state:
  // the toggle is ephemeral chart preference, not a shareable deep-link.
  const [showNav, setShowNav] = useState(false);

  // Flow-adjusted TWR series — shared hook/key (one fetch also feeds any
  // other consumer on the same window). "ALL" → the endpoint's 3650-day max.
  const { data, isLoading, isError, isPlaceholderData } = useTwrSeries({
    portfolioId,
    days: periodDays ?? TWR_MAX_DAYS,
  });

  // R4 hardening: the merge pass is O(n·dates) — memoised on SERIES IDENTITY
  // (query result), the toggle flags, the NAV toggle, and benchmarkCloses
  // (referentially stable via useBenchmarkSeries' combine memoisation).
  // MUST live above the early returns (rules-of-hooks).
  const rows = useMemo(
    () => buildTwrChartRows(data?.points ?? [], showNav, benchmarks, benchmarkCloses),
    [data, showNav, benchmarks, benchmarkCloses],
  );

  // 2026-06-11 Wave 3: dates where the series shows a cash-flow artifact
  // (deposit counted as return / TWR moving on frozen NAV). Memoised with
  // the same identity as rows — one O(n) pass per fetched series.
  const artifactDates = useMemo(
    () => findFlowArtifactDates(data?.points ?? []),
    [data],
  );

  // First-ever fetch only — period switches keep the previous chart drawn
  // (placeholderData in useTwrSeries), so this skeleton can never flash
  // mid-session.
  if (isLoading) {
    return <Skeleton className="h-[202px] w-full" data-testid="twr-chart-skeleton" />;
  }

  if (isError || !data) {
    return (
      <div className="h-[202px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-negative font-mono">
          Couldn&apos;t load TWR series.
        </p>
      </div>
    );
  }

  if (rows.length === 0) {
    // Named empty state — the TWR series needs snapshots before a return
    // series exists. NEVER draw a fabricated flat line.
    return (
      <div
        data-testid="twr-chart-empty"
        className="h-[202px] flex items-center justify-center border border-border rounded-[2px]"
      >
        <EmptyState
          condition="empty-no-data"
          copyKey="portfolio.analytics-insufficient"
          icon={LineChartIcon}
        />
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
      portfolio: "TWR",
      nav: "NAV (unadj.)",
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
      // R3 polish: while placeholderData shows the PREVIOUS period's series,
      // dim the chart (opacity-60 + transition) as the subtle "updating"
      // affordance — stale data beats an unmount flash, but it must be
      // visually distinguishable from settled data.
      data-stale={isPlaceholderData || undefined}
      className={cn(
        "border border-border rounded-[2px] transition-opacity overflow-hidden",
        isPlaceholderData && "opacity-60",
      )}
      data-testid="twr-chart"
    >
      {/* ── Honest header (22px): names exactly what the line is ──────────
          "TWR — FLOW-ADJUSTED" replaces the old "CUM. RETURN" hedge — the
          series IS flow-adjusted now. flow_days quantifies how many days in
          the window had external flows (i.e. how much the NAV line lies). */}
      <div className="flex h-[22px] items-center justify-between border-b border-border bg-card px-2">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          TWR — flow-adjusted
          {data.flow_days > 0 && (
            <span
              className="ml-2 normal-case tracking-normal text-muted-foreground/70"
              title="Days in this window with external deposits/withdrawals — the TWR line excludes their effect; the NAV line includes it."
            >
              {data.flow_days} flow day{data.flow_days === 1 ? "" : "s"}
            </span>
          )}
          {/* 2026-06-11 Wave 3: named data-quality warning. The line is still
              drawn (hiding the chart would hide the evidence), but the user
              must know the series contains unadjusted flows — the live demo
              series jumps +116% on a funding day. Warning token (amber), not
              negative: this is a data caveat, not a loss. */}
          {artifactDates.length > 0 && (
            <span
              data-testid="twr-flow-artifact-warning"
              className="ml-2 normal-case tracking-normal text-warning"
              title={`The TWR series contains ${artifactDates.length} suspected cash-flow artifact${artifactDates.length === 1 ? "" : "s"} (deposit/position import counted as return) on: ${artifactDates.join(", ")}. Jumps on these dates are NOT performance. Backend series fix pending.`}
            >
              ⚠ {artifactDates.length} flow artifact{artifactDates.length === 1 ? "" : "s"}
            </span>
          )}
        </span>
        {/* NAV toggle — same pill affordance as the SPY/QQQ benchmark
            toggles in AnalyticsTab so the interaction is recognisable.
            aria-pressed exposes the state to AT + tests. */}
        <button
          type="button"
          data-testid="nav-line-toggle"
          aria-pressed={showNav}
          title={`${showNav ? "Hide" : "Show"} the unadjusted NAV-return line (includes deposits/withdrawals — the pre-TWR approximation)`}
          onClick={() => setShowNav((v) => !v)}
          className={cn(
            "text-[10px] font-mono px-1.5 py-px rounded-[2px] border transition-colors",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            showNav
              ? "border-primary text-primary bg-primary/10"
              : "border-border/60 text-muted-foreground hover:text-foreground hover:border-border",
          )}
        >
          NAV
        </button>
      </div>

      <div
        role="img"
        aria-label={`Portfolio flow-adjusted TWR for ${period} period${showNav ? " with unadjusted NAV line" : ""}${benchmarks.SPY ? " with SPY overlay" : ""}${benchmarks.QQQ ? " with QQQ overlay" : ""}`}
        className="h-[180px]"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
            <XAxis
              dataKey="date"
              // R3 polish (ADR-F-15): axis tick labels are numeric data —
              // font-mono via the CSS variable so they match every other
              // number on the page (recharts inlines tick style as SVG attrs).
              tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--font-mono)" }}
              tickLine={false}
              axisLine={false}
              // ≤5 x-ticks (design spec §4.3) — same density as the old chart.
              interval={Math.max(0, Math.floor(rows.length / 5) - 1)}
              // "YYYY-MM-DD" → "MM-DD" for compact tick labels.
              tickFormatter={(v: string) => (typeof v === "string" ? v.slice(5) : v)}
            />
            <YAxis
              tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--font-mono)" }}
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

            {/* Annotation lines first so the TWR line draws ON TOP of them. */}
            {benchmarks.SPY && (
              <Line
                type="monotone"
                dataKey="spy"
                stroke={COLOR_SPY}
                strokeWidth={1}
                strokeDasharray="4 2" // dashed = benchmark convention
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
            {/* NAV (unadjusted) — dotted, muted: a diagnostic, not a hero. */}
            {showNav && (
              <Line
                type="monotone"
                dataKey="nav"
                stroke={COLOR_NAV}
                strokeWidth={1}
                strokeDasharray="1 3" // dotted ≠ dashed benchmarks — third visual class
                dot={false}
                connectNulls
              />
            )}

            {/* Portfolio TWR — the hero line: solid, brightest, thickest. */}
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
    </div>
  );
}
