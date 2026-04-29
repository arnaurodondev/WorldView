/**
 * components/portfolio/DividendIncomeTimeline.tsx — YTD dividend chart + table (PLAN-0053 T-B-2-06)
 *
 * WHY THIS EXISTS: Dividend-paying portfolios (REITs, dividend-growth, ETFs)
 * need a quarterly cadence view to track income flow. The Transactions tab
 * lists individual dividend rows but never tells the user "you received $X
 * this year, mostly from ABC and XYZ". This widget answers exactly that.
 *
 * WHY QUARTERLY (not monthly): most US/EU equities pay on a quarterly cadence;
 * a quarterly bar chart aligns the visual rhythm with the underlying business
 * reality. Monthly bars would be sparse and misleading (e.g. $0 in any month
 * a holding doesn't pay).
 *
 * WHY PER-TICKER TABLE BELOW THE CHART:
 *   The chart shows the temporal shape; the table shows the source. Both
 *   answer different questions and live cleanly stacked: "when?" + "from who?".
 *
 * WHY ANNUALIZED-YIELD ESTIMATE NOT INCLUDED v1:
 *   The estimate requires current price × annualized dividend rate, which
 *   needs a quote round-trip per ticker — added complexity for a metric
 *   that's already on the holdings table. Skipped per scope; can layer on
 *   in a follow-up.
 *
 * WHO USES IT: portfolio/page.tsx — Holdings tab (mountable below activity feed)
 * DATA SOURCE: getTransactions() filtered to type==DIVIDEND
 * DESIGN REFERENCE: PLAN-0053 §T-B-2-06
 */

"use client";
// WHY "use client": uses recharts (a browser-only DOM API), useState, useMemo.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatPrice, cn } from "@/lib/utils";

// ── Props / Types ────────────────────────────────────────────────────────────

export interface DividendIncomeTimelineProps {
  /** Portfolio UUID. */
  portfolioId: string | null | undefined;
}

interface QuarterBucket {
  /** "2026 Q1" — display label and group key */
  quarter: string;
  /** Sum of all DIVIDEND payments received in the quarter (USD-equivalent assumed). */
  total: number;
}

interface TickerBucket {
  ticker: string;
  /** YTD total received from this ticker. */
  total: number;
  /** Number of payments received — useful for "X payments" UX. */
  count: number;
}

// We pull a generous limit so we can compute YTD aggregates client-side;
// the backend doesn't expose a "by-quarter" endpoint yet.
const TX_FETCH_LIMIT = 500;

// Sortable columns in the per-ticker breakdown.
type TickerSortKey = "total" | "ticker" | "count";

// ── Component ────────────────────────────────────────────────────────────────

export function DividendIncomeTimeline({
  portfolioId,
}: DividendIncomeTimelineProps) {
  const { accessToken } = useAuth();

  // Sort state for the per-ticker table. WHY default to "total desc": the
  // most useful question is "who pays me the most?", which is total-desc.
  const [sortKey, setSortKey] = useState<TickerSortKey>("total");
  const [sortDesc, setSortDesc] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["dividend-timeline-transactions", portfolioId, TX_FETCH_LIMIT],
    queryFn: () =>
      createGateway(accessToken).getTransactions(portfolioId!, {
        limit: TX_FETCH_LIMIT,
        offset: 0,
      }),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // ── Derive quarterly + per-ticker buckets ──────────────────────────────
  const { quarterly, perTicker, ytdTotal } = useMemo(() => {
    const dividends = (data?.transactions ?? []).filter(
      (tx) => tx.type === "DIVIDEND",
    );
    // Filter to YTD = current calendar year. WHY YTD-only: the spec asks for
    // YTD; a wider window would dilute the most-recent-quarter signal that
    // matters for cashflow planning.
    const yearStart = new Date(new Date().getUTCFullYear(), 0, 1).getTime();
    const ytd = dividends.filter(
      (tx) => Date.parse(tx.executed_at) >= yearStart,
    );

    // Quarterly aggregation. We track 4 fixed buckets (Q1..Q4) so the chart
    // shape is stable regardless of which quarter is currently in flight.
    const year = new Date().getUTCFullYear();
    const qBuckets: QuarterBucket[] = [
      { quarter: `${year} Q1`, total: 0 },
      { quarter: `${year} Q2`, total: 0 },
      { quarter: `${year} Q3`, total: 0 },
      { quarter: `${year} Q4`, total: 0 },
    ];

    // Per-ticker aggregation accumulates total + count.
    const tickerMap = new Map<string, TickerBucket>();

    let total = 0;
    for (const tx of ytd) {
      // WHY tx.amount: dividends in S1 use units≈0, price≈0, with the cash
      // amount in `amount`. Falling back to qty * price is wrong for divs.
      const amt = tx.amount ?? 0;
      total += amt;

      const month = new Date(tx.executed_at).getUTCMonth(); // 0-11
      const qIdx = Math.floor(month / 3); // 0..3
      qBuckets[qIdx]!.total += amt;

      const t = tx.ticker || "—";
      const existing = tickerMap.get(t);
      if (existing) {
        existing.total += amt;
        existing.count += 1;
      } else {
        tickerMap.set(t, { ticker: t, total: amt, count: 1 });
      }
    }

    return {
      quarterly: qBuckets,
      perTicker: Array.from(tickerMap.values()),
      ytdTotal: total,
    };
  }, [data]);

  // Apply sort to per-ticker rows. WHY a separate memo: the table's sort
  // state changes more often than the underlying data, keeping the heavy
  // aggregation memo stable lets us re-sort without reaggregating.
  const sortedTickers = useMemo(() => {
    const arr = [...perTicker];
    arr.sort((a, b) => {
      let diff = 0;
      if (sortKey === "ticker") diff = a.ticker.localeCompare(b.ticker);
      else if (sortKey === "count") diff = a.count - b.count;
      else diff = a.total - b.total;
      return sortDesc ? -diff : diff;
    });
    return arr;
  }, [perTicker, sortKey, sortDesc]);

  if (!portfolioId) return null;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col bg-background" data-testid="dividend-timeline">
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          DIVIDEND INCOME — YTD
        </span>
        <span className="font-mono text-[11px] tabular-nums text-foreground">
          {formatPrice(ytdTotal)}
        </span>
      </div>

      {isLoading && (
        <div className="space-y-1 p-2">
          <Skeleton className="h-[120px] w-full" />
          <Skeleton className="h-[22px] w-full" />
          <Skeleton className="h-[22px] w-full" />
        </div>
      )}

      {!isLoading && ytdTotal === 0 && (
        <div className="px-3 py-3">
          <InlineEmptyState message="No dividends received yet" />
        </div>
      )}

      {!isLoading && ytdTotal > 0 && (
        <>
          {/* ── Bar chart ──────────────────────────────────────────────── */}
          {/* WHY h-[140px]: enough vertical room for 4 bars to read clearly
              without dominating the holdings tab. The ResponsiveContainer
              handles width responsively. */}
          <div className="h-[140px] px-2 py-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={quarterly} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                {/* WHY no axis lines / dashed grid: matches the rest of the
                    portfolio analytics charts (terminal density, minimal
                    chrome). The grid is a faint horizontal reference only. */}
                <CartesianGrid strokeDasharray="2 2" stroke="hsl(var(--border) / 0.4)" vertical={false} />
                <XAxis
                  dataKey="quarter"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `$${v}`}
                  width={50}
                />
                <Tooltip
                  cursor={{ fill: "hsl(var(--muted) / 0.3)" }}
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    fontSize: 11,
                    fontFamily: "var(--font-mono, monospace)",
                  }}
                  formatter={(value: number) => [formatPrice(value), "Dividends"]}
                />
                {/* WHY bg-primary fill: dividends are positive cashflow — using
                    the primary brand colour signals "this is a good thing"
                    without overloading the positive-green semantic that's
                    reserved for P&L. */}
                <Bar dataKey="total" fill="hsl(var(--primary))" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* ── Per-ticker breakdown table ─────────────────────────────── */}
          <div className="border-t border-border/40">
            <table className="w-full border-collapse text-[11px]">
              <thead>
                <tr className="h-6 border-b border-border/60">
                  <SortableHeader
                    label="TICKER"
                    activeKey={sortKey}
                    desc={sortDesc}
                    columnKey="ticker"
                    onSort={(k) => {
                      if (sortKey === k) setSortDesc(!sortDesc);
                      else {
                        setSortKey(k);
                        setSortDesc(true);
                      }
                    }}
                    align="left"
                  />
                  <SortableHeader
                    label="PAYMENTS"
                    activeKey={sortKey}
                    desc={sortDesc}
                    columnKey="count"
                    onSort={(k) => {
                      if (sortKey === k) setSortDesc(!sortDesc);
                      else {
                        setSortKey(k);
                        setSortDesc(true);
                      }
                    }}
                    align="right"
                  />
                  <SortableHeader
                    label="YTD TOTAL"
                    activeKey={sortKey}
                    desc={sortDesc}
                    columnKey="total"
                    onSort={(k) => {
                      if (sortKey === k) setSortDesc(!sortDesc);
                      else {
                        setSortKey(k);
                        setSortDesc(true);
                      }
                    }}
                    align="right"
                  />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {sortedTickers.map((row) => (
                  <tr key={row.ticker} className="h-7 hover:bg-muted/30">
                    <td className="px-2 font-mono text-[11px] font-bold tabular-nums text-primary">
                      {row.ticker}
                    </td>
                    <td className="px-2 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                      {row.count}
                    </td>
                    <td className="px-2 text-right font-mono text-[11px] tabular-nums text-foreground">
                      {formatPrice(row.total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ── SortableHeader ───────────────────────────────────────────────────────────

interface SortableHeaderProps {
  label: string;
  activeKey: TickerSortKey;
  desc: boolean;
  columnKey: TickerSortKey;
  onSort: (key: TickerSortKey) => void;
  align: "left" | "right";
}

/**
 * SortableHeader — clickable <th> that toggles sort order.
 *
 * WHY a dedicated sub-component: keeps the JSX concise in the main render and
 * gives us a single place to apply the active-arrow indicator without the
 * three columns drifting visually.
 */
function SortableHeader({
  label,
  activeKey,
  desc,
  columnKey,
  onSort,
  align,
}: SortableHeaderProps) {
  const isActive = activeKey === columnKey;
  return (
    <th
      className={cn(
        "px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal cursor-pointer select-none hover:text-foreground",
        align === "left" ? "text-left" : "text-right",
      )}
      onClick={() => onSort(columnKey)}
      aria-sort={isActive ? (desc ? "descending" : "ascending") : "none"}
    >
      {label}
      {/* Arrow indicator — only on the active column. */}
      {isActive && (
        <span className="ml-1 text-foreground" aria-hidden="true">
          {desc ? "↓" : "↑"}
        </span>
      )}
    </th>
  );
}
