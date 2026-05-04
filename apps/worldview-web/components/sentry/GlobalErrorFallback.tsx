/**
 * components/sentry/GlobalErrorFallback.tsx — Fallback UI for the root Sentry ErrorBoundary
 *
 * WHY THIS COMPONENT EXISTS:
 * React's ErrorBoundary pattern catches unhandled render errors and shows a
 * fallback instead of a blank white screen. Sentry's ErrorBoundary (used in
 * providers.tsx) needs a `fallback` prop — this is that fallback.
 *
 * WHAT HAPPENS ON ERROR:
 *   1. A child component throws during render
 *   2. Sentry.ErrorBoundary catches it via componentDidCatch()
 *   3. Sentry SDK sends the error to the Sentry dashboard (async, non-blocking)
 *   4. React re-renders with this component as the entire page content
 *   5. Sam sees a clean message and a "Reload" button (not a blank page)
 *
 * WHY "The error has been reported":
 * Transparency — Sam (the paying user) should know we saw the error and it
 * is actionable on our end. Reduces support burden ("I got a blank page").
 *
 * WHY window.location.reload() NOT React router push:
 * The error may have corrupted the React state tree. A full page reload
 * re-initialises everything from scratch — the safest recovery path.
 *
 * PLAN-0065 T-D-02, PRD-0034 §3 FR-T3-1
 */

"use client";

// WHY "use client": this component uses onClick (browser event) and
// window.location.reload() — browser-only APIs. It cannot be a Server Component.

export function GlobalErrorFallback() {
  // The "Reload" handler triggers a hard page reload, not a Next.js client
  // navigation. A hard reload re-fetches the HTML from the server and boots
  // a fresh React tree — correct when the in-memory tree is in an error state.
  function handleReload() {
    window.location.reload();
  }

  return (
    // WHY role="alert": the WCAG 2.1 "status" role announces the message to
    // screen readers immediately when the component mounts, without the user
    // needing to focus it first. Essential for keyboard / AT users who would
    // otherwise see no feedback that the page changed.
    <div
      role="alert"
      className={[
        // Full-viewport centred layout so the message is clearly visible
        // even when the rest of the page has collapsed
        "flex min-h-screen flex-col items-center justify-center gap-4",
        // Terminal-grade dark background consistent with the Midnight Pro theme
        "bg-background text-foreground",
        // Monospace font matches the terminal design canon (DESIGN_SYSTEM.md)
        "font-mono",
      ].join(" ")}
    >
      {/* Primary message — intentionally short; no stack trace visible to user */}
      <p className="text-sm text-muted-foreground">
        Something went wrong. The error has been reported.
      </p>

      {/* Reload CTA — visually matches the terminal's button style */}
      <button
        onClick={handleReload}
        className={[
          "rounded border border-border px-4 py-2 text-xs",
          "hover:bg-accent hover:text-accent-foreground",
          "transition-colors duration-150",
          // Focus ring for keyboard accessibility
          "focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        ].join(" ")}
        type="button"
      >
        Reload
      </button>
    </div>
  );
}
