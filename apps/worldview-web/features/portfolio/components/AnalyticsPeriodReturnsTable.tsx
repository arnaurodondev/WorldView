/**
 * features/portfolio/components/AnalyticsPeriodReturnsTable.tsx
 *
 * WHY THIS EXISTS: Provides the "Time Period Analyzer" view familiar from IBKR
 * Portfolio Analyst. A single compact table where each row shows the portfolio
 * return for a standard period vs a benchmark. Traders use this to answer:
 * "Did I beat SPY over 1M / 3M / YTD / 1Y?" without navigating between charts.
 *
 * DATA SOURCE:
 *   - Fetches value-history at each standard period individually.
 *   - Computes period return client-side from first/last value point.
 *   - Benchmark column uses the TWR endpoint when available; currently shows "—"
 *     until the backend endpoint ships (Decision 2 fallback in design spec).
 *
 * WHY one query per period (not one bundle query): TanStack Query's per-entry
 * caching means the 1Y fetch is not re-triggered when only the 1M period changes
 * on the performance chart. Each row is independent and can go stale separately.
 *
 * WHY 7 rows (not the 9 IBKR shows): We use the same 7 periods as
 * AnalyticsPeriodSelector. "3Y" and "ITD" are deferred until the backend
 * provides a reliable long-horizon snapshot history.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3 "PERIOD RETURNS"
 */
"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
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
const PERIODS = [
  { label: "1M",  days: 30 },
  { label: "3M",  days: 90 },
  { label: "6M",  days: 180 },
  { label: "YTD", days: null }, // server computes YTD from Jan 1
  { label: "1Y",  days: 365 },
  { label: "2Y",  days: 730 },
  { label: "ALL", days: null }, // full history
] as const;

// ── Helper: single period query ───────────────────────────────────────────────

/**
 * Single-period value history query — used per row.
 *
 * WHY inline hook-like pattern (not a custom hook): React rules of hooks
 * require all hooks to be called unconditionally. We cannot call useQuery
 * inside a loop. Instead we define a component per row that runs its own
 * query and renders directly. This keeps the code simple and within React's
 * rules.
 */
interface PeriodRowProps {
  portfolioId: string;
  label: string;
  days: number | null;
  accessToken: string | null;
}

// ── Formatting helpers ────────────────────────────────────────────────────────

function fmtReturn(v: number | null): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(2);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

function returnColorClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── PeriodRow component ───────────────────────────────────────────────────────

/**
 * PeriodRow — renders a single row in the period returns table.
 *
 * WHY a separate component per row: allows each row to run its own useQuery.
 * React hooks cannot be called conditionally or inside loops — extracting each
 * row as a component is the idiomatic pattern for "N independent queries".
 *
 * Each row fetches its period's value-history. Many rows will share cache entries
 * with the performance chart (same portfolioId+period key), so cold-start cost
 * is bounded to the number of unique periods NOT already cached.
 */
function PeriodRow({ portfolioId, label, days, accessToken }: PeriodRowProps) {
  const params = useMemo(
    () => ({
      ...(days != null ? { days } : {}),
      granularity: "1d" as const,
    }),
    [days],
  );

  const { data, isLoading } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, label),
    queryFn: () =>
      createGateway(accessToken).getValueHistory(portfolioId, params),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // Compute the period return from value-history.
  const periodReturn = useMemo(() => {
    const pts = data?.points ?? [];
    if (pts.length < 2) return null;
    const first = pts[0].value;
    const last = pts[pts.length - 1].value;
    if (first === 0) return null;
    return (last - first) / first;
  }, [data]);

  if (isLoading) {
    return (
      <tr className="h-[24px]">
        <td className="pr-3"><Skeleton className="h-3 w-6" /></td>
        <td className="pr-3"><Skeleton className="h-3 w-12" /></td>
        <td className="pr-3"><Skeleton className="h-3 w-12" /></td>
        <td><Skeleton className="h-3 w-12" /></td>
      </tr>
    );
  }

  const display = fmtReturn(periodReturn);
  const colorClass = returnColorClass(periodReturn);

  return (
    <tr className="h-[24px] border-b border-border/40 last:border-0">
      {/* Period label */}
      <td className="text-muted-foreground pr-3 py-0.5">
        {label}
      </td>
      {/* Portfolio return */}
      <td className={cn("pr-3 py-0.5 tabular-nums", colorClass)}>
        {display}
      </td>
      {/* vs SPY — placeholder until TWR endpoint ships.
          WHY "—" not "N/A": "—" is the universal absent-value glyph used
          throughout the app. "N/A" implies the value will never exist. */}
      <td className="pr-3 py-0.5 text-muted-foreground tabular-nums">—</td>
      {/* Excess return — also unavailable until TWR endpoint ships */}
      <td className="py-0.5 text-muted-foreground tabular-nums">—</td>
    </tr>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsPeriodReturnsTable({
  portfolioId,
}: AnalyticsPeriodReturnsTableProps) {
  const { accessToken } = useAuth();

  return (
    <div className="border border-border rounded-[2px] overflow-hidden">
      {/* WHY <table> with <thead>/<tbody>/<tfoot>: the design spec requires
          an accessible table element so screen readers announce the column
          headers. A pure CSS grid would require aria-rowheader markup to
          achieve the same a11y. */}
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
          {PERIODS.map((p) => (
            <PeriodRow
              key={p.label}
              portfolioId={portfolioId}
              label={p.label}
              days={p.days}
              accessToken={accessToken}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
