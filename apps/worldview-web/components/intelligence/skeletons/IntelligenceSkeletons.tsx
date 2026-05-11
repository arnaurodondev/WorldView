/**
 * components/intelligence/skeletons/IntelligenceSkeletons.tsx — Per-panel skeletons
 * (PLAN-0074 Wave H T-H-07)
 *
 * WHY SKELETONS:
 * Bloomberg-grade UX rule: never show a blank panel. Every data surface must have
 * a loading skeleton that matches the approximate shape of its content. This prevents
 * layout shifts and communicates to analysts that data is loading (not broken).
 *
 * WHY ONE FILE (not per-panel files):
 * All four panel skeletons are small (< 20 lines each) and are only used in one
 * place (the page's loading states). Splitting them into four files would add
 * navigation overhead without any meaningful separation. Single file, named exports.
 *
 * DESIGN: Skeletons match the STATIC pattern (no animate-pulse) from skeleton.tsx:
 * Bloomberg terminals use static skeleton bars — animation implies activity.
 */

import { Skeleton } from "@/components/ui/skeleton";

// ── Graph panel skeleton ──────────────────────────────────────────────────────

/** GraphPanelSkeleton — gray rectangle filling the graph column */
export function GraphPanelSkeleton() {
  return (
    <div className="h-full p-3 flex flex-col gap-2">
      {/* Controls toolbar skeleton */}
      <Skeleton className="h-[28px] w-full" />
      {/* Graph area skeleton — fills remaining height */}
      <Skeleton className="flex-1 w-full" />
    </div>
  );
}

// ── Intelligence panel skeleton ───────────────────────────────────────────────

/** IntelligencePanelSkeleton — tabs bar + table row shimmer */
export function IntelligencePanelSkeleton() {
  return (
    <div className="h-full p-3 flex flex-col gap-2">
      {/* Tab bar skeleton */}
      <div className="flex gap-1">
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-16" />
        <Skeleton className="h-7 w-24" />
      </div>
      {/* Table rows skeleton */}
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="h-[22px] w-full" />
      ))}
    </div>
  );
}

// ── Sidebar skeleton ──────────────────────────────────────────────────────────

/** EntitySidebarSkeleton — 3 stacked rectangles matching sidebar sections */
export function EntitySidebarSkeleton() {
  return (
    <div className="p-3 space-y-4">
      {/* Header: health ring + entity name */}
      <div className="flex items-center gap-3">
        <Skeleton className="h-12 w-12 rounded-full shrink-0" />
        <div className="space-y-1.5 flex-1">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      {/* Narrative section */}
      <Skeleton className="h-[80px] w-full" />
      {/* Sparkline */}
      <Skeleton className="h-[40px] w-full" />
      {/* Source bars */}
      <Skeleton className="h-[60px] w-full" />
    </div>
  );
}

// ── Chat panel skeleton ───────────────────────────────────────────────────────

/** EntityChatPanelSkeleton — input placeholder + message list skeleton */
export function EntityChatPanelSkeleton() {
  return (
    <div className="h-[200px] flex flex-col">
      {/* Header */}
      <Skeleton className="h-8 w-full rounded-none" />
      {/* Message area */}
      <div className="flex-1 p-3 space-y-2">
        <Skeleton className="h-[24px] w-1/3 ml-auto" />
        <Skeleton className="h-[32px] w-2/3" />
      </div>
      {/* Input area */}
      <Skeleton className="h-[44px] w-full rounded-none" />
    </div>
  );
}
