/**
 * app/error.tsx — Global error boundary for unexpected runtime errors
 *
 * WHY THIS EXISTS: Next.js 15 App Router renders this file when an unhandled
 * exception is thrown during render or data-fetching in a route segment.
 * It acts as a React Error Boundary — catching render-time exceptions and
 * showing a recovery UI instead of a blank/white screen.
 *
 * WHY "use client": Next.js requires error.tsx to be a Client Component.
 * Error boundaries in React can only be class components or the React
 * error boundary hook — both require the client runtime. Next.js enforces
 * this by mandating "use client" at the top of error.tsx files.
 * See: https://nextjs.org/docs/app/building-your-application/routing/error-handling
 *
 * WHY reset() prop: Next.js provides `reset` as a prop to error.tsx.
 * Calling it attempts to re-render the failed segment from scratch — useful
 * for transient errors like network blips or flaky S9 responses.
 * If the same error re-occurs after reset(), the error boundary shows again.
 *
 * WHY GENERIC MESSAGE: We never show raw JavaScript error messages to users.
 * Stack traces / internal error details could leak implementation details or
 * confuse non-technical users. The generic message is intentional.
 *
 * WHO USES IT: React / Next.js runtime on any unhandled throw in a route.
 * DATA SOURCE: None — receives Next.js-provided `error` and `reset` props.
 * DESIGN REFERENCE: PRD-0028 §6.5 "Page: Error States"
 */

"use client";
// WHY "use client": required by Next.js for error.tsx — see docstring above.

import { useEffect } from "react";
import Link from "next/link";
import { XCircle } from "lucide-react";

// ── Props interface ───────────────────────────────────────────────────────────

/**
 * ErrorPageProps — Next.js-injected props for the global error boundary
 *
 * WHY these exact prop names: Next.js 15 injects exactly `error` and `reset`.
 * Renaming them would break the interface contract with the framework.
 */
interface ErrorPageProps {
  error: Error & { digest?: string }; // digest: optional opaque server-side error ID
  reset: () => void;                  // retry — re-renders the failed segment
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  // WHY useEffect: logs the real error to the browser console so developers can
  // see the actual stack trace. The UI shows a generic message intentionally.
  // WHY unconditional (not dev-only): makes it debuggable in both dev and production.
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary caught]", error.message, error);
  }, [error]);

  return (
    // WHY min-h-screen + flex + items-center: vertically centres the error card
    // on the full viewport height. This page renders outside the (app) layout
    // (no sidebar, no TopBar) — the layout itself may have caused the error.
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="text-center space-y-6 max-w-sm">
        {/* ── Icon ─────────────────────────────────────────────────────────── */}
        {/* WHY XCircle (red): an unexpected error is more severe than a 404.
            The negative color (#EF5350 via text-negative) signals "stop and take action". */}
        <XCircle
          className="mx-auto h-12 w-12 text-negative/60"
          aria-hidden="true"
        />

        {/* ── Heading ──────────────────────────────────────────────────────── */}
        <div className="space-y-2">
          <p className="text-xs font-mono text-muted-foreground tracking-widest uppercase">
            Something went wrong
          </p>
          <h1 className="text-[24px] font-semibold text-foreground">
            Unexpected error
          </h1>
          <p className="text-[14px] text-muted-foreground">
            An unexpected error occurred. This has been logged automatically.
            You can try again or return to the dashboard.
          </p>
        </div>

        {/* ── Actions ──────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-3">
          {/* WHY button (not Link): reset() is a function call to re-render
              the failed component tree — not a navigation event. Using <button>
              with type="button" is the correct semantic element. */}
          <button
            type="button"
            onClick={reset}
            // WHY rounded-[2px] (was rounded-md=6px): Terminal Dark sharp
            // corners across the platform; the 6px curve was a consumer-app
            // throwback. Aligns with the design system rule that all radii
            // be 2px (or rounded-full for avatars).
            className="inline-flex items-center justify-center rounded-[2px] bg-primary px-5 py-2 text-[14px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Try again
          </button>
          {/* WHY also show a Link: if reset() throws the same error again,
              the user needs an escape path. /dashboard is the stable home base. */}
          <Link
            href="/dashboard"
            className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline transition-colors"
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
