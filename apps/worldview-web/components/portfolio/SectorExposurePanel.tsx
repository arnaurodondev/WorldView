/**
 * SectorExposurePanel — per-sector weight + live day-change block for the
 * Holdings overview band. (REWRITTEN 2026-06-10 sprint, Wave 2 — the previous
 * dot-list version was orphaned after BottomInfoStrip was removed; this file
 * had zero consumers and zero tests, so the rewrite breaks no call sites.)
 *
 * WHY THIS EXISTS: the SECTOR donut (page header) and SectorAllocationBar
 * (10px stacked bar) compress sector data into shapes the user can't read
 * numbers from. This panel shows the top sectors as proper rows:
 *
 *   SECTOR          ▮▮▮▮▮▮  43.9%   +$312.40
 *   (name, truncate) (weight bar+%)  (day Δ$, colored)
 *
 * BENCHMARK GAP (honest): no S9 endpoint exposes SPY/benchmark sector
 * weights, so a portfolio-vs-SPY weight comparison CANNOT be drawn from
 * real data. Per the sprint brief we show weight + day-change per sector
 * instead and name the gap in the footer caption — we never fabricate
 * index composition data.
 *
 * DATA SOURCE:
 *   - segments: GET /v1/portfolios/{id}/sector-breakdown (server weights,
 *     sorted largest-first, 60s Valkey cache) — passed down from
 *     usePortfolioData, no extra fetch.
 *   - day Δ$: computeSectorStats joins segment.instrument_ids (sprint gap
 *     #2 — exact UUID join, no name aliasing) with live quotes × quantity.
 *     null (old S9 build / quotes not yet arrived) renders "—".
 *
 * WHO USES IT: features/portfolio/components/HoldingsTab.tsx (overview band).
 * DESIGN REFERENCE: DS §6.2 skeletons, ADR-F-15 mono numbers, 22px rows.
 */
"use client";
// WHY "use client": rendered inside the client HoldingsTab tree and uses
// useMemo over live-quote props.

import { useMemo } from "react";
// formatPercentUnsigned for WEIGHT (a "+43.9%" allocation would be a category
// error — weights have no direction); signed formatPercent for the day Δ%.
import { cn, formatPercent, formatPercentUnsigned } from "@/lib/utils";
import { fmtPnl } from "@/components/portfolio/holdings-columns";
import {
  computeSectorStats,
  type SectorQuote,
} from "@/features/portfolio/lib/sector-stats";
import type { Holding, SectorBreakdownSegment } from "@/types/api";

interface SectorExposurePanelProps {
  /** Server sector-breakdown segments (largest-first). undefined = loading. */
  segments?: SectorBreakdownSegment[];
  /** Current holdings — quantity source for the day-change join. */
  holdings: Holding[];
  /** Live quotes keyed by instrument_id (change drives day Δ$). */
  quotes: Record<string, SectorQuote>;
  /** True while the breakdown query is in flight. */
  isLoading?: boolean;
}

/** Max rows that fit the 128px band: header 22 + 4×22 + caption 16. */
const MAX_ROWS = 4;

export function SectorExposurePanel({
  segments,
  holdings,
  quotes,
  isLoading,
}: SectorExposurePanelProps) {
  // Pure join — memoised on real inputs so the 15s quote poll only
  // recomputes when the quotes object actually changed identity.
  const rows = useMemo(
    () => computeSectorStats(segments ?? [], holdings, quotes),
    [segments, holdings, quotes],
  );

  const visible = rows.slice(0, MAX_ROWS);
  const overflow = rows.length - visible.length;

  return (
    <div
      data-testid="sector-exposure-panel"
      className="flex h-[128px] flex-col bg-card overflow-hidden"
    >
      {/* ── Accent header ── */}
      <div className="flex h-[22px] shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          Sector Exposure
        </span>
        {/* "+N more" — quantifies the hidden tail so the top-4 view is never
            mistaken for the whole book. Full list lives in the donut legend. */}
        {overflow > 0 && (
          <span className="font-mono text-[9px] text-muted-foreground">
            +{overflow} more
          </span>
        )}
      </div>

      {/* ── Body ── */}
      {isLoading || segments == null ? (
        // DS §6.2: static 22px row bars matching the populated layout —
        // no pulse animation on portfolio data surfaces.
        <div data-testid="sector-exposure-skeleton" aria-hidden="true" className="px-3 py-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center">
              <div className="h-2.5 w-full rounded-[2px] bg-muted/30" />
            </div>
          ))}
        </div>
      ) : visible.length === 0 ? (
        // Named empty state — an empty portfolio genuinely has no sectors.
        <div className="flex flex-1 items-center justify-center">
          <span className="font-mono text-[11px] text-muted-foreground">
            No sector data yet.
          </span>
        </div>
      ) : (
        <>
          <div className="flex flex-col px-3 py-px">
            {visible.map((row) => (
              <div
                key={row.sector}
                data-testid={`sector-row-${row.sector}`}
                className="flex h-[22px] items-center gap-2"
              >
                {/* Sector name — flex-1 + truncate + full name in tooltip
                    (truncation convention: never clip without a tooltip). */}
                <span
                  className="min-w-0 flex-1 truncate text-[11px] text-foreground"
                  title={`${row.sector} — ${row.count} position${row.count === 1 ? "" : "s"}`}
                >
                  {row.sector}
                </span>

                {/* Weight bar — fixed 48px track so all bars share a scale
                    (same convention as the holdings WEIGHT column). */}
                <div className="w-[48px] h-[3px] rounded-[1px] bg-muted/50 shrink-0">
                  <div
                    className="h-full rounded-[1px] bg-primary/50"
                    style={{ width: `${Math.min(row.weight * 100, 100).toFixed(1)}%` }}
                  />
                </div>
                <span className="w-[44px] shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                  {formatPercentUnsigned(row.weight)}
                </span>

                {/* Day Δ$ — live, colored. null = "we don't know" (no
                    instrument_ids from an old S9 build, or quotes not yet
                    arrived) → "—", never a fabricated $0.00. */}
                <span
                  className={cn(
                    "w-[72px] shrink-0 text-right font-mono text-[11px] tabular-nums",
                    row.dayChangeValue == null
                      ? "text-muted-foreground"
                      : row.dayChangeValue >= 0
                        ? "text-positive"
                        : "text-negative",
                  )}
                  title={
                    row.dayChangePct != null
                      ? `Day change: ${formatPercent(row.dayChangePct)}`
                      : undefined
                  }
                >
                  {row.dayChangeValue == null ? "—" : fmtPnl(row.dayChangeValue)}
                </span>
              </div>
            ))}
          </div>

          {/* ── Benchmark-gap caption (honest, named) ── */}
          <div className="mt-auto flex h-[16px] shrink-0 items-center px-3">
            <span className="truncate text-[9px] text-muted-foreground/70">
              Weight + day Δ shown — benchmark sector weights unavailable from any endpoint.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
