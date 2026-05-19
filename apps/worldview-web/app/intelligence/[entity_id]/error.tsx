"use client"
// WHY "use client": error.tsx MUST be a Client Component — Next.js App Router
// enforces this because error boundaries require React class component semantics
// (componentDidCatch), which the framework emulates via a client boundary.
// Server Components cannot catch their own errors in the same segment.

/**
 * app/intelligence/[entity_id]/error.tsx — Error boundary for the entity
 * intelligence page.
 *
 * WHY THIS EXISTS: Without error.tsx, any uncaught error in page.tsx or its
 * Server Components bubbles all the way up to the root layout error boundary,
 * replacing the entire shell (nav, sidebar) with a generic error page. This
 * file catches errors scoped to the intelligence route so the user sees a
 * contextual message and can recover without losing the shell chrome.
 *
 * WHY TWO RECOVERY ACTIONS:
 *   "Try again" — calls reset() which re-renders page.tsx in place. Useful
 *     for transient S9 timeouts or network blips.
 *   "Back to news" — navigates to /news so the user can continue working
 *     without being stranded on a broken entity URL.
 *
 * WHO USES IT: app/intelligence/[entity_id]/ route.
 */

import { useRouter } from "next/navigation"

export default function IntelligenceError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const router = useRouter()

  return (
    // WHY h-full: matches loading.tsx so both states occupy the same viewport
    // area. Prevents layout shift when transitioning from loading → error.
    <div className="flex h-full flex-col items-center justify-center gap-3">
      <p className="text-[12px] text-muted-foreground">
        Entity not found or unavailable.
      </p>

      {/* Show the error message when available — helps during development and
          when the entity ID is malformed (404 from S9). */}
      {error.message && (
        <p className="max-w-[300px] text-center text-[10px] text-muted-foreground/60">
          {error.message}
        </p>
      )}

      <div className="flex gap-2">
        {/* Try again — re-renders the page segment in place (transient errors). */}
        <button
          onClick={reset}
          className="h-7 rounded-[2px] border border-border px-3 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Try again
        </button>

        {/* Back to news — safe exit for permanent errors (entity not found). */}
        <button
          onClick={() => router.push("/news")}
          className="h-7 rounded-[2px] border border-border px-3 text-[11px] text-muted-foreground hover:text-foreground"
        >
          Back to news
        </button>
      </div>
    </div>
  )
}
