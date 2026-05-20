"use client";
/**
 * app/(app)/search/error.tsx — Search route error boundary (HIGH-009 / FR-9.2)
 */

import { useRouter } from "next/navigation";

export default function RouteError({
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
        <p className="max-w-[300px] text-center text-[10px] text-muted-foreground/60">
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
