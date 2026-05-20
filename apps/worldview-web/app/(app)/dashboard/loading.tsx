/**
 * app/(app)/dashboard/loading.tsx — Streaming dashboard skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: Next.js App Router uses loading.tsx as the Suspense fallback
 * while the page's server data fetches in flight. Without it, every navigation
 * to /dashboard shows a blank white flash before content paints. Finance
 * dashboards are dense — even 100ms blank flash feels broken.
 *
 * WHY THREE CARDS: matches the 12-col dashboard layout.
 * Row 1: main widget (8 cols) + secondary widget (4 cols)
 * Row 2: full-width strip (12 cols)
 * Heights mirror the actual widget content areas so no layout shift on hydration.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardLoading() {
  return (
    <div className="grid grid-cols-12 gap-2 p-3">
      {/* Row 1: main content area */}
      <div className="col-span-12 xl:col-span-8">
        <Skeleton className="h-[200px] w-full rounded-[2px]" />
      </div>
      {/* Row 1: secondary panel */}
      <div className="col-span-12 xl:col-span-4">
        <Skeleton className="h-[200px] w-full rounded-[2px]" />
      </div>
      {/* Row 2: full-width strip (market snapshot / movers) */}
      <div className="col-span-12">
        <Skeleton className="h-[120px] w-full rounded-[2px]" />
      </div>
    </div>
  );
}
