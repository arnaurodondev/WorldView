/**
 * components/ui/skeleton.tsx — Loading skeleton component
 *
 * WHY THIS EXISTS: Every data panel in the finance terminal must show a loading
 * state while fetching. Empty panels are confusing for finance users who expect
 * Bloomberg-style "loading..." indicators. Skeletons provide visual structure
 * while data loads, reducing perceived latency.
 *
 * Rule: Never show a blank panel. Always show Skeleton while isLoading.
 * DESIGN REFERENCE: CLAUDE.md "Every data surface: loading skeleton + error state"
 */

import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        // WHY no animate-pulse: Bloomberg terminals use STATIC skeleton bars — no movement.
        // Finance users interpret animation as "something is happening" (streaming, thinking).
        // Static bars make the loading state feel intentional, not broken.
        // Custom skeleton-pulse keyframe remains in globals.css for opt-in use via className.
        // bg-muted: elevated surface color from Bloomberg Dark (#1A2030)
        "rounded-[2px] bg-muted",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
