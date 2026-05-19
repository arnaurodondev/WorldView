/**
 * app/(app)/alerts/loading.tsx — Alerts/News page loading state (CRIT-005 / FR-9.1)
 *
 * WHY centered spinner: the alerts page has three tabs (Alerts | News Feed | Top Today)
 * with different data shapes. A unified spinner is simpler and avoids premature
 * commitment to one tab's content shape before the auth+data state is resolved.
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
