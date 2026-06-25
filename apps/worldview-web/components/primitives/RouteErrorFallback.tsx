/**
 * components/primitives/RouteErrorFallback.tsx — shared route-level error UI
 *
 * WHY THIS EXISTS (Round-4 hardening): every route segment that defines an
 * `error.tsx` needs the same four elements — a named state (which surface
 * broke), an icon, a "Try again" button wired to Next.js' `reset()` callback,
 * and the error digest for debugging. Before this primitive each route hand-
 * rolled its own variant (app/(app)/news/error.tsx, .../alerts/error.tsx, …)
 * with drifting styles. New boundaries (the (app) group fallback, indices)
 * compose this primitive instead so the pattern is defined exactly once.
 *
 * WHY A PRIMITIVE AND NOT AN error.tsx ITSELF: Next.js error files must be
 * route-segment files; a shared component can't be one directly. But an
 * error.tsx can be a 10-line wrapper that renders this component — that is
 * the documented pattern (DESIGN_SYSTEM.md §6.7.1).
 *
 * WHY "use client": error.tsx files are mandatory Client Components in the
 * App Router (they are React error boundaries under the hood), so everything
 * they render must be client-safe. We also use useEffect for logging.
 *
 * DESIGN (Terminal Dark):
 *   - AlertTriangle in warning tone — a recoverable route error is less
 *     severe than the full-app crash (app/error.tsx uses the red XCircle).
 *   - font-mono uppercase micro-labels, rounded-[2px], muted palette.
 *   - digest rendered small (9px mono) — it is a support/debug artifact,
 *     not user-facing copy, but having it visible lets a user paste it
 *     into a bug report ("error digest NEXT-1234…").
 */

"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface RouteErrorFallbackProps {
  /**
   * Next.js-injected error. `digest` is the opaque server-side error ID that
   * Next.js attaches to errors thrown in Server Components (the real message
   * is stripped in production for safety — the digest is the only correlation
   * handle, which is exactly why we surface it).
   */
  error: Error & { digest?: string };
  /**
   * Next.js-injected retry callback — re-renders the failed segment from
   * scratch. Correct recovery for transient failures (network blip, flaky S9
   * response). If the segment throws again, the boundary re-appears.
   */
  reset: () => void;
  /**
   * Named state — which surface failed (e.g. "INDICES", "SETTINGS").
   * Rendered as the uppercase mono micro-label so the user (and a screenshot
   * in a bug report) immediately identifies the broken surface.
   */
  routeLabel: string;
  /**
   * Escape hatch if reset() keeps failing. Defaults to the dashboard —
   * the platform's stable home base.
   */
  homeHref?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RouteErrorFallback({
  error,
  reset,
  routeLabel,
  homeHref = "/dashboard",
}: RouteErrorFallbackProps) {
  // WHY console.error in an effect: the UI deliberately shows a generic
  // message (raw error text can leak internals / confuse users), so the real
  // error must still reach the developer console. Sentry capture is handled
  // upstream by Sentry.ErrorBoundary in app/providers.tsx — duplicating
  // captureException here would double-report every route error.
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(`[RouteErrorBoundary:${routeLabel}]`, error);
  }, [error, routeLabel]);

  return (
    // WHY h-full (not min-h-screen): route-level boundaries render INSIDE the
    // (app) shell — TopBar/sidebar survive because error.tsx only replaces the
    // failed segment's children, not the layouts above it. Filling the content
    // area keeps the terminal chrome intact so the user never loses context.
    <div
      className="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 px-6"
      role="alert"
    >
      {/* Icon — warning tone; route errors are recoverable, not fatal. */}
      <AlertTriangle className="h-8 w-8 text-warning/60" aria-hidden="true" />

      {/* Named state — uppercase mono micro-label, terminal convention. */}
      <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {routeLabel} — error
      </p>

      <h2 className="text-sm font-medium text-foreground">
        This panel failed to render
      </h2>

      <p className="max-w-[340px] text-center text-[11px] text-muted-foreground">
        Something went wrong loading this view. The rest of the terminal is
        unaffected — you can retry this panel or go back to the dashboard.
      </p>

      {/* Actions — Try again first (primary recovery), escape hatch second. */}
      <div className="flex items-center gap-2 pt-1">
        {/* WHY <button> (not Link): reset() is a re-render call, not a
            navigation. type="button" prevents accidental form submission if
            a boundary ever ends up inside a form. */}
        <button
          type="button"
          onClick={reset}
          className="h-7 rounded-[2px] border border-border bg-card px-3 text-[11px] text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          Try again
        </button>
        <Link
          href={homeHref}
          className="h-7 rounded-[2px] border border-border px-3 text-[11px] leading-7 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          Back to dashboard
        </Link>
      </div>

      {/* Digest — small, mono, muted. Only renders when Next.js attached one
          (server-thrown errors). Users can quote it in bug reports; we never
          show error.message in production UI (information-leak hygiene). */}
      {error.digest && (
        <p className="pt-2 font-mono text-[9px] text-muted-foreground/50">
          digest: {error.digest}
        </p>
      )}
    </div>
  );
}
