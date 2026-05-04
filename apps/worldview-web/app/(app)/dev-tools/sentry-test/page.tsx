/**
 * app/(app)/dev-tools/sentry-test/page.tsx — Dev-only Sentry smoke test route
 *
 * WHY THIS PAGE EXISTS:
 * Verifying Sentry integration requires firing a real (synthetic) exception and
 * confirming it appears in the Sentry dashboard within 60 seconds. This page
 * provides a single-button UI to trigger that smoke test manually, without
 * needing to break real functionality.
 *
 * WHY "dev-tools" FOLDER (NOT "_dev"):
 * Next.js uses the underscore prefix ("_dev") as the Private Folders convention:
 * files in underscore-prefixed folders are excluded from routing entirely.
 * We WANT this route to be routable in development/staging (so we can visit it
 * in a browser) but 404 in production. Using a regular folder + notFound() at
 * request time achieves this:
 *   - dev build: NODE_ENV = "development" → notFound() skipped → route accessible
 *   - production build: NODE_ENV = "production" → notFound() fires on first render
 *
 * WHY "use client":
 * The throw-on-click handler uses browser state (the button click event). Server
 * Components cannot have onClick handlers. Making the entire page a Client
 * Component keeps the file small and co-locates the prod-guard with the button.
 *
 * WHY process.env.NODE_ENV check at render (not build) time:
 * In Client Components, process.env.NODE_ENV is replaced at BUILD TIME by the
 * Next.js / Webpack bundler. So:
 *   - In a dev build: the `if` becomes `if ("development" === "production")` → never fires
 *   - In a production build: the `if` becomes `if ("production" === "production")` → always fires
 * This is compile-time dead-code elimination — the notFound() call is baked into
 * the production bundle and fires on every render of this page in production.
 *
 * PLAN-0065 T-D-02, PRD-0034 §3 FR-T3-1 (acceptance: "synthetic exception captured
 * in Sentry within 60s")
 */

"use client";

import { notFound } from "next/navigation";

export default function SentryTestPage() {
  // Guard: 404 in production. In dev/staging this line is compiled away
  // (process.env.NODE_ENV is a compile-time constant in Next.js).
  // See module docstring for why this works correctly in both environments.
  if (process.env.NODE_ENV === "production") {
    notFound();
  }

  // Click handler that intentionally throws an unhandled error.
  //
  // WHY throw in onClick (not a useEffect):
  // We want the error to propagate through React's event handling so it is
  // caught by the nearest React ErrorBoundary (Sentry.ErrorBoundary in
  // providers.tsx). A throw inside useEffect would become an unhandled
  // promise rejection which bypasses React's boundary mechanism.
  //
  // WHY include new Date().toISOString() in the message:
  // Makes each test throw unique — prevents Sentry's event deduplication from
  // grouping multiple smoke-test fires into one event. Each click = one Sentry event.
  function triggerSentryError(): never {
    throw new Error("W9 Sentry smoke test " + new Date().toISOString());
  }

  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center gap-6 font-mono"
      data-testid="sentry-test-page"
    >
      {/* Page heading — clearly dev-only so no confusion if someone navigates here */}
      <h1 className="text-lg font-semibold text-muted-foreground">
        Sentry Smoke Test (dev only)
      </h1>

      <p className="max-w-sm text-center text-sm text-muted-foreground">
        Click the button to throw a synthetic error. It should appear in the
        Sentry dashboard within ~60 seconds. The page will also show the{" "}
        <code className="text-xs">GlobalErrorFallback</code> component.
      </p>

      {/* The trigger button — each click fires a unique error event to Sentry */}
      <button
        onClick={triggerSentryError}
        className={[
          "rounded border border-destructive px-4 py-2 text-sm text-destructive",
          "hover:bg-destructive hover:text-destructive-foreground",
          "transition-colors duration-150",
          "focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        ].join(" ")}
        type="button"
        data-testid="sentry-trigger-button"
      >
        Trigger Sentry error
      </button>
    </div>
  );
}
