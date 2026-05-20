/**
 * app/(app)/workspace/loading.tsx — Workspace page loading state (CRIT-005 / FR-9.1)
 *
 * WHY centered spinner: the workspace has a dynamic panel layout loaded from
 * localStorage. We can't replicate the panel positions in a skeleton without
 * reading localStorage at render time (which breaks SSR). The spinner is the
 * correct fallback until the workspace shell hydrates client-side.
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
