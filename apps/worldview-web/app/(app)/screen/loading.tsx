/**
 * app/(app)/screen/loading.tsx — Screen redirect loading state (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: /screen is a 307 redirect to /screener (LOW-010).
 * The redirect happens server-side, so this loading state shows only during
 * the brief interval before the redirect resolves.
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
