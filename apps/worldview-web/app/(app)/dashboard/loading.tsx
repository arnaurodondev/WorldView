/**
 * app/(app)/dashboard/loading.tsx — Streaming dashboard skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: Next.js App Router uses loading.tsx as the Suspense fallback
 * while the page's server data fetches in flight. Without it, every navigation
 * to /dashboard shows a blank flash before content paints. Finance dashboards
 * are dense — even 100ms blank flash feels broken.
 *
 * ROUND 3 (item 3 — shape-matched skeletons): the placeholder grid now mirrors
 * the REAL 4-row dashboard layout from page.tsx (it previously described an
 * 8+4 / 12 layout retired several waves ago, so the skeleton visibly re-laid
 * out into the 4-row grid on hydration):
 *   Row 1 (col-12)                       : Morning Brief
 *   Row 2 (col-2 · col-3 · col-4 · col-3): Clock · Snapshot · Heatmap · Signals
 *   Row 3 (4 × col-3)                    : Portfolio · Positions · Markets · Movers
 *   Row 4 (4 × col-3)                    : Econ · Earnings · News · Alerts
 * Heights mirror page.tsx's gridTemplateRows budgets (Row 2 = 130px fixed;
 * Rows 3/4 use the minmax() minimums) so hydration swaps panels in-place.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardLoading() {
  return (
    // gap-3 + p-3 match page.tsx exactly (it uses gap-3, not the gap-2 this
    // fallback previously carried) — identical gutters are what make the
    // skeleton→content swap read as "fill in" instead of "re-layout".
    <div className="grid grid-cols-12 gap-3 bg-background p-3">
      {/* Row 1: Morning Brief — full width, ~90px collapsed-card footprint */}
      <div className="col-span-12">
        <Skeleton className="h-[90px] w-full rounded-[2px]" />
      </div>

      {/* Row 2: macro-context band — fixed 130px in the real grid */}
      <div className="col-span-2">
        <Skeleton className="h-[130px] w-full rounded-[2px]" />
      </div>
      <div className="col-span-3">
        <Skeleton className="h-[130px] w-full rounded-[2px]" />
      </div>
      <div className="col-span-4">
        <Skeleton className="h-[130px] w-full rounded-[2px]" />
      </div>
      <div className="col-span-3">
        <Skeleton className="h-[130px] w-full rounded-[2px]" />
      </div>

      {/* Row 3: 4 equal panels — minmax(220px, 1fr) in the real grid */}
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={`r3-${i}`} className="col-span-3">
          <Skeleton className="h-[220px] w-full rounded-[2px]" />
        </div>
      ))}

      {/* Row 4: 4 equal panels — minmax(200px, 1fr) in the real grid */}
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={`r4-${i}`} className="col-span-3">
          <Skeleton className="h-[200px] w-full rounded-[2px]" />
        </div>
      ))}
    </div>
  );
}
