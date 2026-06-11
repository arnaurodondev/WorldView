/**
 * features/portfolio/components/AnalyticsPeriodReturnsTable.tsx
 *
 * WHY THIS EXISTS: Provides the "Time Period Analyzer" view familiar from IBKR
 * Portfolio Analyst. A single compact table where each row shows the portfolio
 * return for a standard period vs a benchmark. Traders use this to answer:
 * "Did I beat SPY over 1M / 3M / YTD / 1Y?" without navigating between charts.
 *
 * UPGRADED 2026-06-10 (sprint gap #3 — the TWR endpoint shipped):
 *   - RETURN column is now the FLOW-ADJUSTED TWR per window
 *     (GET /v1/portfolios/{id}/twr?days=N — first point rebased to 0, so the
 *     last point's cumulative value IS the window return). The previous
 *     value-history first/last approximation counted deposits as returns.
 *   - "vs SPY" and "EXCESS" were dead "—" columns ("until the TWR endpoint
 *     ships") — they now compute from real SPY daily closes over the SAME
 *     calendar window (windowReturnFromCloses, unit-tested). ALL keeps "—"
 *     for the benchmark: an open-ended window has no defined SPY span.
 *
 * WHY useQueries instead of per-row PeriodRow components (D-002 refactor):
 * each entry in the queries array has its own queryKey/isLoading/data —
 * independent caching — while keeping all rendering in one component and
 * exposing data-testid="period-row-{PERIOD}" for the test suite.
 *
 * WHY 8 rows (not the 9 IBKR shows): same 8 periods as
 * AnalyticsPeriodSelector. "3Y" and "ITD" are deferred until the backend
 * provides a reliable long-horizon snapshot history.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3 "PERIOD RETURNS"
 */
"use client";

import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { windowReturnFromCloses } from "@/features/portfolio/lib/period-returns";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsPeriodReturnsTableProps {
  portfolioId: string;
}

// ── Period definitions ────────────────────────────────────────────────────────

// WHY separate type from the selector's PERIODS const: this table has fixed
// display rows; the selector provides the interactive state.
// days=null rows resolve at render time: YTD = days since Jan 1; ALL = the
// TWR endpoint's 3650-day maximum (10y — beyond any realistic retail book).
const PERIODS = [
  { label: "1W",  days: 7 },
  { label: "1M",  days: 30 },
  { label: "3M",  days: 90 },
  { label: "6M",  days: 180 },
  { label: "YTD", days: null },
  { label: "1Y",  days: 365 },
  { label: "2Y",  days: 730 },
  { label: "ALL", days: null },
] as const;

/** TWR endpoint maximum window — the honest stand-in for "ALL". */
const TWR_MAX_DAYS = 3650;

/** Days since Jan 1 (≥1 so the endpoint validator never sees 0). */
function ytdDays(): number {
  const now = new Date();
  const jan1 = Date.UTC(now.getUTCFullYear(), 0, 1);
  return Math.max(1, Math.ceil((now.getTime() - jan1) / 86_400_000));
}

/** Concrete fetch window for a row. */
function rowDays(label: string, days: number | null): number {
  if (days != null) return days;
  return label === "YTD" ? ytdDays() : TWR_MAX_DAYS;
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtReturn(v: number | null): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(2);
  // R3 polish: ZERO stays unsigned ("0.00%") — signedPrice convention (R1);
  // a flat period has no direction so "+0.00%" would mislead.
  return v > 0 ? `+${pct}%` : `${pct}%`;
}

/** Signed percentage-point string for the EXCESS column ("+1.30pp"). */
function fmtExcess(v: number | null): string {
  if (v == null) return "—";
  const pp = (v * 100).toFixed(2);
  return v > 0 ? `+${pp}pp` : `${pp}pp`;
}

function returnColorClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsPeriodReturnsTable({
  portfolioId,
}: AnalyticsPeriodReturnsTableProps) {
  // WHY useApiClient (Wave G QA D1): provider-memoised gateway shared across
  // every queryFn in the useQueries array.
  const apiClient = useApiClient();

  // WHY useQueries (D-002): fires 8 independent TWR queries in one hook call.
  // Each entry has its own queryKey, so each period's cache entry is
  // independent. The results array is index-aligned with PERIODS.
  const results = useQueries({
    queries: PERIODS.map((p) => {
      const days = rowDays(p.label, p.days);
      return {
        // 2026-06-10: qk.portfolios.twr — shared with AnalyticsTwrChart for
        // coinciding windows (e.g. the 3M pill), one fetch feeds both.
        queryKey: qk.portfolios.twr(portfolioId, days),
        queryFn: () => apiClient.getTwr(portfolioId, days),
        enabled: !!portfolioId,
        staleTime: 60_000,
        // WHY retry: 1 — table cell gracefully degrades to "—"; prevents a
        // 24-call retry storm on transient backend errors (DS-005): default
        // retry 3 × 8 parallel queries vs capped 16 worst-case.
        retry: 1,
      };
    }),
  });

  // ── SPY closes for the benchmark columns (one fetch, all rows) ──────────
  // Window: 740 days back — covers the longest CONCRETE row (2Y = 730) plus
  // weekend slack. The ALL row keeps "—" (open-ended window; fetching 10y of
  // SPY for one usually-empty cell isn't worth the payload).
  const { data: idMap } = useQuery({
    // Same key as useBenchmarkSeries' resolve step — shared cache entry.
    queryKey: ["benchmark-resolve-batch", ["SPY"]],
    queryFn: () => apiClient.resolveTickersBatch(["SPY"]),
    staleTime: 24 * 60 * 60 * 1000,
    enabled: !!portfolioId,
    retry: false,
  });
  const spyId = idMap?.["SPY"] ?? null;
  const spyFromDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 740);
    return d.toISOString().slice(0, 10);
  }, []);
  const { data: spyOhlcv } = useQuery({
    queryKey: ["benchmark-ohlcv", "SPY", spyId, spyFromDate],
    queryFn: () =>
      apiClient.getOHLCV(spyId!, { timeframe: "1D", start: spyFromDate }),
    enabled: Boolean(spyId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const spyCloses: DatedValue[] = useMemo(
    () =>
      (spyOhlcv?.bars ?? [])
        .map((b: { timestamp: string; close: number }) => ({
          date: b.timestamp.slice(0, 10),
          value: b.close,
        }))
        .sort((a: DatedValue, b: DatedValue) =>
          a.date < b.date ? -1 : a.date > b.date ? 1 : 0,
        ),
    [spyOhlcv],
  );

  // ── Aggregate error state ────────────────────────────────────────────────
  // WHY aggregate (Wave G QA D8/D9): when every period query fails (e.g. S9
  // outage), surface a single inline error instead of eight empty cells. We
  // only show the error when ALL queries fail — partial failures still let
  // the user read the periods that did load.
  const allErrored = results.length > 0 && results.every((r) => r.isError);

  if (allErrored) {
    return (
      <div
        role="alert"
        className="border border-border rounded-[2px] px-3 py-4 text-[11px] text-negative font-mono"
      >
        Couldn&apos;t load period returns
      </div>
    );
  }

  return (
    <div className="border border-border rounded-[2px] overflow-hidden">
      {/* WHY <table> with <thead>/<tbody>: the design spec requires an accessible
          table element so screen readers announce the column headers. */}
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="border-b border-border bg-muted/20">
            <th className="text-left text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal w-[60px]">
              PERIOD
            </th>
            {/* 2026-06-10 honest relabel: the column IS flow-adjusted TWR now
                (previously a NAV first/last approximation labelled RETURN). */}
            <th
              className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal"
              title="Flow-adjusted time-weighted return — deposits/withdrawals excluded"
            >
              TWR
            </th>
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              vs SPY
            </th>
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              EXCESS
            </th>
          </tr>
        </thead>
        <tbody>
          {PERIODS.map((p, i) => {
            const { data, isLoading } = results[i];

            // Skeleton row while this period's fetch is in-flight.
            if (isLoading) {
              return (
                <tr key={p.label} className="h-[24px]">
                  <td className="pr-3"><Skeleton className="h-3 w-6" /></td>
                  <td className="pr-3"><Skeleton className="h-3 w-12" /></td>
                  <td className="pr-3"><Skeleton className="h-3 w-12" /></td>
                  <td><Skeleton className="h-3 w-12" /></td>
                </tr>
              );
            }

            // Window TWR: the endpoint rebases the series to 0 at window
            // start, so the LAST point's cumulative value IS the window
            // return. <2 points = no return derivable → "—".
            const pts = data?.points ?? [];
            const periodReturn =
              pts.length >= 2 ? pts[pts.length - 1].twr_cum : null;

            // Benchmark over the SAME calendar window. ALL stays null (no
            // defined window); windowReturnFromCloses also nulls windows the
            // SPY series doesn't cover — never a mislabelled figure.
            const benchmark =
              p.label !== "ALL" && spyCloses.length >= 2
                ? windowReturnFromCloses(spyCloses, rowDays(p.label, p.days))
                : null;
            const excess =
              periodReturn != null && benchmark != null
                ? periodReturn - benchmark
                : null;

            return (
              // WHY data-testid: lets the test suite assert each period row
              // is present by label without fragile text/CSS selectors.
              <tr
                key={p.label}
                data-testid={`period-row-${p.label}`}
                className="h-[24px] border-b border-border/40 last:border-0"
              >
                <td className="text-muted-foreground pr-3 py-0.5">{p.label}</td>
                <td className={cn("pr-3 py-0.5 tabular-nums text-right", returnColorClass(periodReturn))}>
                  {fmtReturn(periodReturn)}
                </td>
                {/* vs SPY — real closes over the same window (2026-06-10). */}
                <td className="pr-3 py-0.5 text-muted-foreground tabular-nums text-right">
                  {fmtReturn(benchmark)}
                </td>
                {/* Excess = TWR − SPY, in percentage points. */}
                <td
                  className={cn(
                    "py-0.5 tabular-nums text-right px-2",
                    returnColorClass(excess),
                  )}
                >
                  {fmtExcess(excess)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
