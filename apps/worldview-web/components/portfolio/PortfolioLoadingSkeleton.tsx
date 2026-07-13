/**
 * components/portfolio/PortfolioLoadingSkeleton.tsx — mode-aware initial-load
 * skeleton for the portfolio page (PLAN-0122 W-B, T-A-B-02).
 *
 * WHY EXTRACTED (was inline in page.tsx): the loading placeholder must now mirror
 * the ACTIVE mode's above-fold shape — 8 KPI tiles + a donut placeholder in
 * Advanced, but only 4 tiles and NO donut in Simple. Pulling it into a tiny pure
 * component (a) keeps the two explicit shapes readable, and (b) makes them unit-
 * testable without mounting the whole data-driven page (which needs the full
 * usePortfolioData + auth + bundle mock harness).
 *
 * WHY the shapes must match the populated strip EXACTLY: any mismatch (tile count,
 * padding, the donut band) causes a layout jump when the real data resolves
 * (F-P-020). The Simple skeleton therefore drops the 8th…5th tiles and the donut
 * band precisely as the Simple render does.
 */

"use client";

import { Skeleton } from "@/components/ui/skeleton";

export interface PortfolioLoadingSkeletonProps {
  /** Active detail level. "simple" → 4 tiles + no donut; "advanced" → 8 + donut. */
  mode: "simple" | "advanced";
}

export function PortfolioLoadingSkeleton({ mode }: PortfolioLoadingSkeletonProps) {
  // Simple shows the 4 casual tiles (Total Value / Day P&L / Unrealised / Cash);
  // Advanced keeps today's full 8-tile band.
  const tileCount = mode === "simple" ? 4 : 8;
  // The donut band only exists in Advanced (Simple hides SectorAllocationDonut),
  // so the Simple skeleton must NOT reserve its space or the header band would
  // jump when data lands.
  const showDonut = mode === "advanced";

  return (
    // WHY p-3 space-y-3: terminal density — 12px padding, 12px gaps.
    <div className="flex flex-col h-full min-h-0 space-y-3 p-3">
      <div className="flex h-9 items-center justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-7 w-36" />
      </div>
      {/* KPI strip skeleton mirrors the populated strip's shape exactly — same
          `divide-x` separator, same px-3/py-1.5 padding — so there is no layout
          shift when the data resolves. The tile count follows the active mode. */}
      <div className="flex items-stretch">
        <div
          data-testid="kpi-strip-skeleton"
          className="flex min-w-0 flex-1 divide-x divide-border border-b border-border"
        >
          {Array.from({ length: tileCount }).map((_, i) => (
            <div key={i} className="flex-1 px-3 py-1.5">
              <Skeleton className="h-3 w-16 mb-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
        {/* Donut skeleton: circle + 3 legend lines — same shape the populated
            SectorAllocationDonut renders while its own query loads. Advanced-only:
            Simple hides the donut, so its placeholder is omitted entirely. */}
        {showDonut && (
          <div
            data-testid="donut-skeleton"
            className="hidden xl:flex w-[400px] shrink-0 items-center gap-2 border-l border-b border-border px-2 py-1"
          >
            <Skeleton className="size-[56px] rounded-full shrink-0" />
            <div className="flex-1 space-y-1">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
        )}
      </div>
      <Skeleton className="h-9 w-80" />
      {/* F-P-020: row skeletons use h-[22px] to match the real holdings row
          height token. Present in both modes (both render a holdings list). */}
      <div className="space-y-px">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[22px] w-full" />
        ))}
      </div>
    </div>
  );
}
