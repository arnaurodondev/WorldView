/**
 * components/dashboard/DashboardSnapshotPrefetcher.tsx — BFF bundle cache warmer
 *
 * WHY THIS EXISTS: The dashboard page is a Next.js Server Component (no "use client").
 * Hooks cannot run in Server Components, so this thin client wrapper fires the
 * useDashboardSnapshot() hook alongside the individual widget queries. It returns
 * null — no visible UI — but warms the TanStack Query cache with all 6 dashboard
 * sub-resources in a single S9 round-trip (PLAN-0070 C-2).
 *
 * WHY A SEPARATE COMPONENT (not hook in page): The dashboard page is intentionally
 * a Server Component so its shell is SSR'd without JS. Making the whole page "use
 * client" would lose that benefit. This component is the minimal client boundary.
 *
 * HOW IT HELPS: On cold start the snapshot fires one bundled request that resolves
 * all 6 widget queries in parallel. Individual widgets also fire their own queries
 * (independent cache keys) so they degrade gracefully if the snapshot fails, but
 * the 1-round-trip path means the trader sees populated widgets faster.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (invisible, renders null)
 * DATA SOURCE: S9 GET /v1/dashboard/snapshot (PLAN-0070 C-2)
 */

"use client";
// WHY "use client": hooks (useDashboardSnapshot, useAuth) require client-side
// rendering. This is the minimal client boundary for the server-component page.

import { useDashboardSnapshot } from "@/features/dashboard/hooks/useDashboardSnapshot";

export function DashboardSnapshotPrefetcher() {
  // WHY call without select(): we want the whole snapshot pre-fetched and
  // stored under qk.dashboard.snapshot() so individual widgets can use it
  // as a fallback data source. No return value needed — side-effect only.
  useDashboardSnapshot();
  return null;
}
