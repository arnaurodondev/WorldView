/**
 * features/portfolio/components/AnalyticsPeriodReturnsTable.tsx
 *
 * WHY THIS EXISTS: Provides the "Time Period Analyzer" view familiar from IBKR
 * Portfolio Analyst. A single compact table where each row shows the portfolio
 * return for a standard period vs a benchmark. Traders use this to answer:
 * "Did I beat SPY over 1M / 3M / YTD / 1Y?" without navigating between charts.
 *
 * DATA SOURCE:
 *   - Fetches value-history at each standard period via useQueries (D-002).
 *   - Computes period return client-side from first/last value point.
 *   - Benchmark column uses the TWR endpoint when available; currently shows "—"
 *     until the backend endpoint ships (Decision 2 fallback in design spec).
 *
 * WHY useQueries instead of per-row PeriodRow components (D-002 refactor):
 * The original design used a separate PeriodRow sub-component per period, each
 * owning its own useQuery. This was architecturally sound (independent cache
 * entries) but created 7 extra component instances per table mount and made
 * integration tests impossible — there was no data-testid to select rows from
 * outside the component tree.
 *
 * useQueries achieves the same independent caching guarantee (each entry in the
 * queries array has its own queryKey, isLoading, and data) while keeping all
 * rendering in one component. This exposes data-testid="period-row-{PERIOD}"
 * which the test suite requires.
 *
 * WHY 8 rows (not the 9 IBKR shows): We use the same 8 periods as
 * AnalyticsPeriodSelector (1W added in the R2 sprint). "3Y" and "ITD" are
 * deferred until the backend provides a reliable long-horizon snapshot
 * history.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3 "PERIOD RETURNS"
 */
"use client";

import { useQueries } from "@tanstack/react-query";

import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsPeriodReturnsTableProps {
  portfolioId: string;
}

// ── Period definitions ────────────────────────────────────────────────────────

// WHY separate type from the selector's PERIODS const: this table has 7 rows
// in a fixed display order; the selector provides the interactive state.
// Having an independent definition means we can add "3Y" to the table without
// touching the interactive selector's period list.
// R2 sprint: "1W" row added — keeps the table in lock-step with the
// AnalyticsPeriodSelector pills (which gained 1W for the TWR chart).
const PERIODS = [
  { label: "1W",  days: 7 },
  { label: "1M",  days: 30 },
  { label: "3M",  days: 90 },
  { label: "6M",  days: 180 },
  { label: "YTD", days: null }, // server computes YTD from Jan 1
  { label: "1Y",  days: 365 },
  { label: "2Y",  days: 730 },
  { label: "ALL", days: null }, // full history
] as const;

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtReturn(v: number | null): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(2);
  // R3 polish: ZERO stays unsigned ("0.00%") — signedPrice convention (R1);
  // a flat period has no direction so "+0.00%" would mislead.
  return v > 0 ? `+${pct}%` : `${pct}%`;
}

function returnColorClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── Period return computation ─────────────────────────────────────────────────

function computePeriodReturn(points: Array<{ value: number }> | undefined): number | null {
  const pts = points ?? [];
  if (pts.length < 2) return null;
  const first = pts[0].value;
  const last = pts[pts.length - 1].value;
  if (first === 0) return null;
  return (last - first) / first;
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsPeriodReturnsTable({
  portfolioId,
}: AnalyticsPeriodReturnsTableProps) {
  // WHY useApiClient (Wave G QA D1): provider-memoised gateway shared across
  // every queryFn in the useQueries array.
  const apiClient = useApiClient();

  // WHY useQueries (D-002): fires 7 independent queries in one hook call.
  // Each entry has its own queryKey, so each period's cache entry is independent —
  // the 1Y fetch is not invalidated when only the 1M period changes on the
  // performance chart above. The results array is index-aligned with PERIODS.
  const results = useQueries({
    queries: PERIODS.map((p) => ({
      queryKey: qk.portfolios.valueHistory(portfolioId, p.label),
      queryFn: () =>
        apiClient.getValueHistory(portfolioId, {
          ...(p.days != null ? { days: p.days } : {}),
          granularity: "1d" as const,
        }),
      enabled: !!portfolioId,
      staleTime: 60_000,
      // WHY retry: 1 — table cell gracefully degrades to "—"; preventing
      // 21-call retry storm on transient backend (DS-005). Default retry: 3
      // × 7 parallel queries = up to 21 concurrent S1 calls on a single
      // 5xx hiccup; capping per-query at 1 keeps the worst-case load to
      // 14 calls and surfaces the partial-failure state faster.
      retry: 1,
    })),
  });

  // ── Aggregate error state ────────────────────────────────────────────────
  // WHY aggregate (Wave G QA D8/D9): when every period query fails (e.g. S9
  // outage), surface a single inline error instead of seven empty cells. We
  // only show the error when ALL queries fail — partial failures still let the
  // user read the periods that did load.
  const allErrored = results.length > 0 && results.every((r) => r.isError);

  // Inline error replaces the entire table when every period failed.
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
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              RETURN
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

            const periodReturn = computePeriodReturn(data?.points);
            const display = fmtReturn(periodReturn);
            const colorClass = returnColorClass(periodReturn);

            return (
              // WHY data-testid: lets the test suite assert each period row
              // is present by label without fragile text/CSS selectors.
              <tr
                key={p.label}
                data-testid={`period-row-${p.label}`}
                className="h-[24px] border-b border-border/40 last:border-0"
              >
                <td className="text-muted-foreground pr-3 py-0.5">{p.label}</td>
                <td className={cn("pr-3 py-0.5 tabular-nums", colorClass)}>{display}</td>
                {/* vs SPY — placeholder until TWR endpoint ships. */}
                <td className="pr-3 py-0.5 text-muted-foreground tabular-nums">—</td>
                {/* Excess return — unavailable until TWR endpoint ships */}
                <td className="py-0.5 text-muted-foreground tabular-nums">—</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
