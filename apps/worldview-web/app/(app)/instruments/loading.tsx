/**
 * app/(app)/instruments/loading.tsx — Instruments list loading state (CRIT-005 / FR-9.1)
 *
 * WHY centered spinner: the instruments list uses AG Grid with dynamic column sizing.
 * A row-by-row skeleton would require knowing column configuration ahead of time.
 * The AG Grid provides its own internal loading overlay once mounted.
 */

import { Loader2 } from "lucide-react";

export default function Loading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-4 animate-spin text-muted-foreground" />
      <span className="sr-only">Loading...</span>
    </div>
  );
}
