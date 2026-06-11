/**
 * PerformancePeriodsPanel — 1D/1W/1M/3M TWR-vs-SPY comparison rows for the
 * Holdings overview band. (2026-06-10 sprint, Wave 2 portfolio surface.)
 *
 * WHY THIS EXISTS: the overview had no period-return surface at all — the
 * only performance signal was the 1D PerformanceStrip and the $-NAV chart.
 * This panel answers "how am I doing vs the market?" in four rows:
 *
 *   1W   +2.10%   SPY +0.80%   → +1.30pp
 *
 * DATA SOURCE (all real endpoints — nothing fabricated):
 *   - Portfolio side: GET /v1/portfolios/{id}/twr?days=95 via useTwrSeries —
 *     the FLOW-ADJUSTED series (sprint gap #3), so a deposit inside the
 *     window no longer reads as a "return". 95 days covers the longest
 *     window (3M = 91 days) with margin for the carry-forward cutoff rule.
 *   - SPY side: useBenchmarkSeries (ticker → instrument_id resolve + daily
 *     OHLCV closes) over the same calendar span.
 *   - Window math: computePeriodReturns (pure + unit-tested) — geometric
 *     TWR linking, "last point ≤ cutoff" carry-forward, null when a window
 *     isn't genuinely covered by the series.
 *
 * GAP STATES (named, never silent):
 *   - window not covered → "—" on that side ("3M" on a 2-week-old book).
 *   - SPY chain failed   → header caption "SPY unavailable", excess "—".
 *
 * WHO USES IT: features/portfolio/components/HoldingsTab.tsx (overview band).
 * DESIGN REFERENCE: DS §6.2 skeletons, ADR-F-15 mono numbers, 22px rows.
 */
"use client";
// WHY "use client": TanStack Query hooks (useTwrSeries + the SPY queries).

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
// WHY createGateway + useAuth (NOT useBenchmarkSeries/useApiClient): this
// panel mounts on the DEFAULT Holdings tab, whose render tree and page-level
// tests are built on the createGateway pattern (no ApiClientProvider is
// guaranteed there). The two SPY queries below reuse useBenchmarkSeries'
// EXACT query keys, so when the Analytics tab later mounts its overlay the
// closes are already warm in the shared cache — one fetch, two surfaces.
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useTwrSeries } from "@/features/portfolio/hooks/useTwrSeries";
import { computePeriodReturns } from "@/features/portfolio/lib/period-returns";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";

interface PerformancePeriodsPanelProps {
  portfolioId: string | null;
}

/**
 * TWR_WINDOW_DAYS — 95 (not 91): the 3M window-start rule needs a point
 * dated AT OR BEFORE (last − 91d); fetching exactly 91 days would leave the
 * cutoff right at the first point and a weekend gap could push it out of
 * coverage. 4 extra days absorb the longest US-market gap.
 */
const TWR_WINDOW_DAYS = 95;

/** Signed percent for fractions; zero stays unsigned (signedPrice convention). */
function fmtPct(v: number, decimals = 2): string {
  const pct = (v * 100).toFixed(decimals);
  return v > 0 ? `+${pct}%` : `${pct}%`;
}

/** Signed percentage-POINT difference ("+1.30pp"). */
function fmtPp(v: number): string {
  const pp = (v * 100).toFixed(2);
  return v > 0 ? `+${pp}pp` : `${pp}pp`;
}

export function PerformancePeriodsPanel({ portfolioId }: PerformancePeriodsPanelProps) {
  const { accessToken } = useAuth();

  // ── Portfolio TWR series (flow-adjusted, sprint gap #3) ──
  const twrQuery = useTwrSeries({ portfolioId, days: TWR_WINDOW_DAYS });

  // ── SPY closes over the same calendar span ──
  // WHY useMemo on []: keeps the query-key date stable for the session — a
  // raw `new Date()` expression would only change at midnight anyway, and a
  // one-day drift on a 95-day window is immaterial.
  const fromDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - (TWR_WINDOW_DAYS + 7)); // +7: resolve cutoffs near the edge
    return d.toISOString().slice(0, 10);
  }, []);

  // Step 1: SPY ticker → instrument_id. SAME key as useBenchmarkSeries'
  // resolve step so the Analytics tab shares the cache entry. 24h staleTime:
  // instrument IDs never change within a session.
  const {
    data: idMap,
    isError: resolveError,
  } = useQuery({
    queryKey: ["benchmark-resolve-batch", ["SPY"]],
    queryFn: () => createGateway(accessToken).resolveTickersBatch(["SPY"]),
    staleTime: 24 * 60 * 60 * 1000,
    enabled: Boolean(portfolioId) && Boolean(accessToken),
    retry: false,
  });
  const spyId = idMap?.["SPY"] ?? null;

  // Step 2: daily SPY closes. SAME key shape as useBenchmarkSeries' OHLCV
  // step ((ticker, instrumentId, fromDate)) — shared cache, one network hit.
  const { data: spyOhlcv, isError: ohlcvError } = useQuery({
    queryKey: ["benchmark-ohlcv", "SPY", spyId, fromDate],
    queryFn: () =>
      createGateway(accessToken).getOHLCV(spyId!, { timeframe: "1D", start: fromDate }),
    enabled: Boolean(spyId) && Boolean(accessToken),
    staleTime: 5 * 60 * 1000, // daily bars change once per session
    retry: false,
  });

  // ticker → DatedValue[] (ascending) — same normalization useBenchmarkSeries
  // applies (slice defends against full ISO datetimes; ISO dates sort
  // lexicographically = chronologically).
  const spyCloses: DatedValue[] | undefined = useMemo(() => {
    const bars = spyOhlcv?.bars;
    if (!bars || bars.length === 0) return undefined;
    return bars
      .map((b: { timestamp: string; close: number }) => ({
        date: b.timestamp.slice(0, 10),
        value: b.close,
      }))
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  }, [spyOhlcv]);

  // Definitive failure (vs still loading): resolve errored, the OHLCV fetch
  // errored, or the resolve succeeded but SPY has no instrument (its query
  // is permanently disabled). Same semantics as useBenchmarkSeries.
  const spyFailed =
    resolveError || ohlcvError || (idMap != null && !idMap["SPY"]);

  // ── Pure window math (unit-tested in period-returns.test.ts) ──
  const rows = useMemo(
    () => computePeriodReturns(twrQuery.data?.points ?? [], spyCloses),
    [twrQuery.data, spyCloses],
  );

  if (!portfolioId) return null;

  return (
    <div
      data-testid="performance-periods-panel"
      className="flex h-[128px] flex-col bg-card overflow-hidden"
    >
      {/* ── Accent header ── */}
      <div className="flex h-[22px] shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          Performance — TWR vs SPY
        </span>
        {/* Named degradation: a missing overlay must never fail silently
            (the user would read four "—" cells as a bug, not a data gap). */}
        {spyFailed && (
          <span
            role="status"
            data-testid="performance-spy-unavailable"
            className="font-mono text-[9px] uppercase tracking-[0.04em] text-muted-foreground"
            title="SPY price history could not be loaded — portfolio returns are unaffected."
          >
            SPY unavailable
          </span>
        )}
      </div>

      {/* ── Body ── */}
      {twrQuery.isLoading ? (
        // DS §6.2: static 22px row bars matching the populated layout.
        <div data-testid="performance-periods-skeleton" aria-hidden="true" className="px-3 py-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center">
              <div className="h-2.5 w-full rounded-[2px] bg-muted/30" />
            </div>
          ))}
        </div>
      ) : twrQuery.isError ? (
        // Named error + retry (house convention).
        <div
          data-testid="performance-periods-error"
          className="flex flex-1 flex-col items-center justify-center gap-1.5"
        >
          <span className="font-mono text-[11px] text-negative">
            Couldn&apos;t load TWR series.
          </span>
          <button
            type="button"
            aria-label="Retry loading TWR series"
            onClick={() => void twrQuery.refetch()}
            className="flex h-6 items-center rounded-[2px] border border-primary/60 px-2 font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            Retry
          </button>
        </div>
      ) : (twrQuery.data?.points.length ?? 0) < 2 ? (
        // Named gap: a brand-new portfolio has no return series yet.
        <div className="flex flex-1 items-center justify-center px-3 text-center">
          <span className="font-mono text-[10px] text-muted-foreground">
            Not enough history yet — returns appear after 2+ daily snapshots.
          </span>
        </div>
      ) : (
        <div className="flex flex-col px-3 py-1">
          {rows.map((row) => (
            <div
              key={row.label}
              data-testid={`period-row-${row.label}`}
              className="flex h-[24px] items-center gap-2"
            >
              {/* Window label */}
              <span className="w-[24px] shrink-0 font-mono text-[10px] uppercase text-muted-foreground">
                {row.label}
              </span>

              {/* Portfolio TWR — colored; "—" when the window isn't covered
                  (a 2-week-old book has no honest 3M return). */}
              <span
                className={cn(
                  "w-[64px] shrink-0 text-right font-mono text-[11px] tabular-nums",
                  row.portfolio == null
                    ? "text-muted-foreground"
                    : row.portfolio >= 0
                      ? "text-positive"
                      : "text-negative",
                )}
              >
                {row.portfolio == null ? "—" : fmtPct(row.portfolio)}
              </span>

              {/* SPY over the same window — muted (the benchmark must not
                  compete with the book; same treatment as chart overlays). */}
              <span className="min-w-0 flex-1 truncate text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                {row.benchmark == null ? "SPY —" : `SPY ${fmtPct(row.benchmark)}`}
              </span>

              {/* Excess return in percentage points — the actual verdict. */}
              <span
                className={cn(
                  "w-[72px] shrink-0 text-right font-mono text-[11px] tabular-nums",
                  row.excess == null
                    ? "text-muted-foreground"
                    : row.excess >= 0
                      ? "text-positive"
                      : "text-negative",
                )}
                title="Excess return: portfolio TWR − SPY over the same window"
              >
                {row.excess == null ? "—" : `→ ${fmtPp(row.excess)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
