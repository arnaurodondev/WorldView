/**
 * app/not-found.tsx — Global 404 "Page not found" component
 *
 * WHY THIS EXISTS: Next.js 15 App Router automatically renders this file when:
 *   1. A route segment calls `notFound()` from "next/navigation"
 *   2. A URL is requested that has no matching route segment
 *
 * WHY NOT A CLIENT COMPONENT: not-found.tsx can be a Server Component.
 * It has no client-side state or event handlers — pure static markup.
 * Keeping it a Server Component reduces bundle size and allows Next.js
 * to pre-render it as a static page at build time.
 *
 * WHY LINK TO /DASHBOARD (not /): Authenticated users who hit a broken link
 * want to return to the main app, not the marketing landing page.
 * Unauthenticated users hitting /dashboard will be redirected to /login by
 * the (app) layout's auth guard — so the same link works for both cases.
 *
 * WHO USES IT: Any broken URL in the app; any `notFound()` call in server routes.
 * DATA SOURCE: None — static content.
 * DESIGN REFERENCE: PRD-0028 §6.5 "Page: Error States"
 */

import Link from "next/link";
import { AlertTriangle } from "lucide-react";

export default function NotFound() {
  return (
    // WHY min-h-screen + flex + items-center: vertically centres the error card
    // on the full viewport height, regardless of the parent layout. This page
    // renders outside the (app) layout wrapper (no sidebar, no TopBar) because
    // the 404 may occur before authentication or in a layout-breaking route.
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="text-center space-y-6 max-w-sm">
        {/* ── Icon ─────────────────────────────────────────────────────────── */}
        {/* WHY AlertTriangle: communicates "warning, something is wrong" without
            the severity of a full error icon. 404 is recoverable — lost, not broken. */}
        <AlertTriangle
          className="mx-auto h-12 w-12 text-muted-foreground/40"
          aria-hidden="true"
        />

        {/* ── Heading ──────────────────────────────────────────────────────── */}
        {/* WHY "404" as a separate small label: screen readers read the number
            first, then the descriptive text below — clearer than combining them. */}
        <div className="space-y-2">
          <p className="text-xs font-mono text-muted-foreground tracking-widest uppercase">
            Error 404
          </p>
          <h1 className="text-[24px] font-semibold text-foreground">
            Page not found
          </h1>
          <p className="text-[14px] text-muted-foreground">
            The page you&apos;re looking for doesn&apos;t exist or has been moved.
          </p>
        </div>

        {/* ── Actions ──────────────────────────────────────────────────────── */}
        <div className="flex flex-col items-center gap-3">
          {/* WHY bg-primary: primary CTA uses the Terminal Dark trading-yellow
              primary token (#FFD60A) as the recovery action button. */}
          <Link
            href="/dashboard"
            // WHY rounded-[2px] (was rounded-md=6px): Terminal Dark uniform
            // 2px corner radius across the platform.
            className="inline-flex items-center justify-center rounded-[2px] bg-primary px-5 py-2 text-[14px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Back to Dashboard
          </Link>
          {/* WHY secondary link to landing: gives unauthenticated users an
              escape hatch to the marketing page if they don't have an account. */}
          <Link
            href="/"
            className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline transition-colors"
          >
            Go to home
          </Link>
        </div>
      </div>
    </main>
  );
}
