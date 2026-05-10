/**
 * components/instrument/ShortInterestRow.tsx — compact short-interest strip
 *
 * WHY THIS EXISTS (PLAN-0088 Wave G-3): the Fundamentals tab listed share
 * count and float but omitted short interest — the single most-watched
 * sentiment signal on Finviz, Bloomberg Terminal, and Yahoo Finance after
 * earnings dates. Hedge-fund analysts scanning a name look at:
 *   - Float (how many shares actually trade)
 *   - Short Float % (how much of the float is shorted)
 *   - Short Ratio (days-to-cover)
 *   - Short Interest (raw shares)
 *
 * Showing these four numbers in a compact 4-column row matches Finviz's
 * "Short Float / Short Ratio / Short Interest" trio plus float for context,
 * giving a one-glance squeeze read.
 *
 * WHY 4 COLUMNS (not a vertical stack): horizontal scan-row matches the
 * existing PerformanceBar pattern in the platform (8 timeframe chips in a
 * row). Vertical would compete with the OverviewSidebarMetrics rail and
 * doesn't read naturally as "comparable numbers across one dimension".
 *
 * WHY NULL-TOLERANT: EODHD's share-statistics for many tickers return
 * SharesShort=null and ShortRatio=null (data lag from the bi-monthly NYSE
 * settlement cycle). Showing "—" for missing values is the Finviz pattern;
 * suppressing the row entirely would hide the float and short-float % which
 * are usually populated.
 *
 * WHO USES IT: FundamentalsTab (replacing or alongside the existing
 *              ShareStatistics row layout)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrument_id}/share-statistics
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import type { FundamentalsRecord } from "@/types/api";

interface Props {
  instrumentId: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatLargeNumber — render share counts as 14.66B / 1.32M / 723K.
 *
 * WHY thresholds at B/M/K: matches Finviz column conventions; analysts read
 * "14.66B float" instinctively. Going below 1K is rare for traded equities;
 * raw integer is fine in that case.
 */
function formatLargeNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return `${Math.round(value)}`;
}

/**
 * formatDecimalPercent — render a decimal (0.0092) as "0.92%".
 *
 * WHY 2 decimals: short-float-percent values in liquid US equities are
 * typically 0.5%–10%; one decimal hides spread (1.2% vs 1.7% matters for
 * squeeze risk), three decimals add noise.
 */
function formatDecimalPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

/**
 * formatRatio — render days-to-cover with one decimal.
 *
 * WHY 1 decimal: short-ratios cluster around 1.0–10.0; the integer part
 * carries most of the signal but tenths matter when comparing peers.
 */
function formatRatio(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(1);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ShortInterestRow({ instrumentId }: Props) {
  const auth = useAuth();
  const accessToken = auth.accessToken ?? null;

  const query = useQuery({
    queryKey: ["share-statistics", instrumentId],
    queryFn: () =>
      createGateway(accessToken).getShareStatistics(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 6 * 60 * 60 * 1000, // 6h — short data lags bi-monthly anyway
  });

  if (query.isLoading) {
    return (
      <div className="grid grid-cols-4 gap-2 px-3 py-2 border-t border-border">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[36px]" />
        ))}
      </div>
    );
  }

  // WHY render the row even when erroring (with all "—"): keeping the
  // structure visible signals to the user that we attempted to fetch and
  // hit an issue, rather than silently hiding the whole strip.
  const record: FundamentalsRecord | undefined = query.data?.records?.[0];
  const data = record?.data as
    | {
        SharesFloat?: number | null;
        SharesShort?: number | null;
        ShortRatio?: number | null;
        ShortPercentFloat?: number | null;
      }
    | undefined;

  return (
    <div className="grid grid-cols-4 gap-2 px-3 py-2 border-t border-border">
      <Cell label="Float" value={formatLargeNumber(data?.SharesFloat)} />
      <Cell label="Short Float" value={formatDecimalPercent(data?.ShortPercentFloat)} />
      <Cell label="Short Ratio" value={formatRatio(data?.ShortRatio)} />
      <Cell label="Short Int" value={formatLargeNumber(data?.SharesShort)} />
    </div>
  );
}

// ── Cell sub-component ────────────────────────────────────────────────────────

/**
 * Cell — uppercase label + bold tabular-nums value, matching PerformanceBar's
 * cell pattern. Tabular-nums keeps decimals aligned across the 4 columns even
 * when values have different magnitudes.
 */
function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  );
}
