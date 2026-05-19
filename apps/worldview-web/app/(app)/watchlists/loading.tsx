/**
 * app/(app)/watchlists/loading.tsx — Watchlists page loading state (CRIT-005 / FR-9.1)
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
