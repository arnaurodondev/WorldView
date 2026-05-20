/**
 * app/(app)/screener/loading.tsx — Screener page loading state (CRIT-005 / FR-9.1)
 *
 * WHY centered spinner: the screener uses a filter sidebar + AG Grid table.
 * A full-table skeleton would require knowing column widths ahead of time.
 * A centered spinner is the correct fallback here — the AG Grid initializes
 * its own loading overlay once it mounts.
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
