/**
 * app/(app)/portfolio/loading.tsx — Portfolio page skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: /portfolio fans out to 3+ S9 endpoints (holdings, quotes,
 * transactions). The KPI strip + holdings table skeleton prevents blank flash
 * while the waterfall resolves. Heights match actual component heights.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function PortfolioLoading() {
  return (
    <div className="flex flex-col gap-2 p-3">
      {/* KPI strip (portfolio value, P&L, day change) */}
      <Skeleton className="h-[60px] w-full rounded-[2px]" />
      {/* Table header row */}
      <Skeleton className="h-[22px] w-full rounded-[2px]" />
      {/* Holding rows */}
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-[22px] w-full rounded-[2px]" />
      ))}
    </div>
  );
}
