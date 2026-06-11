"use client";
/**
 * app/(app)/dashboard/error.tsx — Dashboard error boundary (HIGH-009 / FR-9.2)
 *
 * WHY "use client": Next.js error boundaries must be client components because
 * they use React state (error.message) and event handlers (reset, router.push).
 *
 * WHY PER-ROUTE: A global error.tsx only catches errors outside the root layout.
 * Per-route error.tsx catches errors within that route's Suspense boundary,
 * allowing the rest of the app (shell, nav rail) to remain interactive while
 * only the failing route shows the recovery UI.
 *
 * WHY "Try again" + "Back to dashboard": the reset() call re-renders the route
 * (triggers a re-fetch). The navigation button is the escape hatch if reset
 * fails repeatedly (e.g. a backend outage).
 */

import { useRouter } from "next/navigation";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <p className="text-[12px] text-muted-foreground">Something went wrong.</p>
      {error.message && (
        <p className="max-w-[300px] text-center text-[10px] text-muted-foreground-dim">
          {error.message}
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={reset}
          className="h-7 rounded-[2px] border border-border px-3 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Try again
        </button>
        <button
          onClick={() => router.push("/dashboard")}
          className="h-7 rounded-[2px] border border-border px-3 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Back to dashboard
        </button>
      </div>
    </div>
  );
}
