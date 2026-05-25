/**
 * features/portfolio/components/AnalyticsAttributionTable.tsx
 *
 * WHY THIS EXISTS: Attribution shows WHAT drove portfolio returns — which holdings
 * (or sectors, or asset classes) contributed the most and least. This is the
 * "Contribution to Return" table from IBKR Portfolio Analyst and Bloomberg PORT.
 * Without it, a PM knows their total return but can't diagnose what produced it.
 *
 * DATA SOURCE:
 *   - Fetches qk.portfolios.attribution(portfolioId, period, dimension)
 *   - Displays top 10 rows sorted by |contrib_bps| descending.
 *   - Graceful degradation: shows "Attribution unavailable" when the endpoint
 *     returns null (planned endpoint not yet shipped).
 *
 * WHY |contrib_bps| sort (not raw contrib_bps): the user wants to see the biggest
 * movers — both top contributors AND worst detractors. Sorting by absolute value
 * puts the rows that mattered most first, regardless of direction. The colour
 * coding (positive/negative) then communicates direction.
 *
 * WHY top 10 max: Bloomberg PORT shows 10-15 rows for holding-level attribution.
 * Beyond 10, the rows represent <1% contributors and add noise without insight.
 * The "dimension = sector" view has at most ~11 GICS sectors so 10 covers nearly
 * all rows anyway.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3, §5.3
 */
"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { AttributionRow } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsAttributionTableProps {
  portfolioId: string;
  /** Active analytics period (e.g. "YTD"). */
  period: string;
  /** Which dimension to break down by. */
  dimension: "holding" | "sector" | "asset_class";
}

// ── Formatting helpers ────────────────────────────────────────────────────────

/** Format contribution in basis points. Positive → "+335 bps", negative → "-58 bps". */
function fmtBps(v: number | null): string {
  if (v == null) return "—";
  const rounded = Math.round(v);
  return v >= 0 ? `+${rounded} bps` : `${rounded} bps`;
}

/** Format weight as percentage. */
function fmtWeight(v: number | null): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

/** Format period return as percentage. */
function fmtReturn(v: number | null): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(1);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

function bpsColorClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsAttributionTable({
  portfolioId,
  period,
  dimension,
}: AnalyticsAttributionTableProps) {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.attribution(portfolioId, period, dimension),
    queryFn: () =>
      createGateway(accessToken).getAttribution(portfolioId, period, dimension),
    enabled: !!accessToken && !!portfolioId,
    // WHY 5min staleTime: attribution is period-bucketed; daily snapshots mean
    // the values only change when a new snapshot runs (nightly). 5min is a
    // reasonable balance between freshness and avoiding redundant re-computation.
    staleTime: 300_000,
    // WHY retry: false — getTwr and getAttribution are planned endpoints that
    // may not exist yet. We want immediate fallback to "unavailable" without
    // 3 retry delays degrading the user experience.
    retry: false,
  });

  // ── Sort by |contrib_bps| descending and cap at 10 rows ──────────────────
  const rows: AttributionRow[] = useMemo(() => {
    const all = data?.rows ?? [];
    return all
      // WHY Math.abs sort: we want the biggest movers first regardless of
      // direction. A row with -335 bps is more significant than +50 bps.
      .sort((a, b) => Math.abs(b.contrib_bps ?? 0) - Math.abs(a.contrib_bps ?? 0))
      .slice(0, 10);
  }, [data]);

  // ── Loading: 5-row skeleton ───────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="border border-border rounded-[2px] overflow-hidden">
        <table className="w-full text-[11px] font-mono border-collapse">
          <thead>
            <tr className="border-b border-border bg-muted/20">
              <th className="text-left text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">NAME</th>
              <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">WEIGHT</th>
              <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">CONTRIB</th>
              <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">RETURN</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 5 }).map((_, i) => (
              <tr key={i} className="h-[24px] border-b border-border/40 last:border-0">
                <td className="px-2 py-0.5"><Skeleton className="h-3 w-20" /></td>
                <td className="px-2 py-0.5"><Skeleton className="h-3 w-10 ml-auto" /></td>
                <td className="px-2 py-0.5"><Skeleton className="h-3 w-14 ml-auto" /></td>
                <td className="px-2 py-0.5"><Skeleton className="h-3 w-10 ml-auto" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  // WHY "Attribution unavailable" (not a generic error): the design spec §7
  // specifies this exact message for the attribution error state. It is more
  // informative than "Something went wrong" — the user knows to expect this
  // for a new portfolio without history.
  if (isError || data === null) {
    return (
      <div
        // WHY data-testid: test assertions check for this element using the
        // data-testid selector to avoid coupling to the exact error message text.
        data-testid="attribution-unavailable"
        className="border border-border rounded-[2px] px-3 py-4 text-[11px] text-muted-foreground font-mono"
      >
        Attribution unavailable
      </div>
    );
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (rows.length === 0) {
    return (
      <div className="border border-border rounded-[2px] px-3 py-4 text-[11px] text-muted-foreground font-mono">
        No attribution data for this period.
      </div>
    );
  }

  // ── Populated table ───────────────────────────────────────────────────────
  return (
    <div className="border border-border rounded-[2px] overflow-hidden">
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="border-b border-border bg-muted/20">
            <th className="text-left text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              NAME
            </th>
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              WEIGHT
            </th>
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              CONTRIB
            </th>
            <th className="text-right text-[10px] text-muted-foreground uppercase tracking-wide px-2 py-1 font-normal">
              RETURN
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const bpsClass = bpsColorClass(row.contrib_bps);

            return (
              <tr
                key={`${row.name}-${idx}`}
                className="h-[24px] border-b border-border/40 last:border-0 hover:bg-muted/10"
              >
                {/* NAME: ticker for holdings, sector name, or asset class label.
                    WHY truncate: the name column is narrow; long sector names like
                    "Information Technology" would overflow without truncation. */}
                <td className="px-2 py-0.5 max-w-[120px]">
                  <span className="block truncate text-foreground">
                    {row.name}
                  </span>
                </td>
                {/* WEIGHT: portfolio allocation as % — rendered in muted colour
                    because it's context data, not a performance indicator. */}
                <td className="px-2 py-0.5 text-right text-muted-foreground tabular-nums">
                  {fmtWeight(row.weight)}
                </td>
                {/* CONTRIB in bps: the load-bearing column — coloured positive/negative. */}
                <td className={cn("px-2 py-0.5 text-right tabular-nums font-semibold", bpsClass)}>
                  {fmtBps(row.contrib_bps)}
                </td>
                {/* RETURN: the holding's own period return (not its contribution). */}
                <td
                  className={cn(
                    "px-2 py-0.5 text-right tabular-nums",
                    row.period_return != null && row.period_return > 0
                      ? "text-positive"
                      : row.period_return != null && row.period_return < 0
                        ? "text-negative"
                        : "text-muted-foreground",
                  )}
                >
                  {fmtReturn(row.period_return)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
