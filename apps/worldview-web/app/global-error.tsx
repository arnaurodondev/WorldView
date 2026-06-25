"use client";
/**
 * app/global-error.tsx — last-resort error boundary (replaces the ROOT layout)
 *
 * WHY THIS EXISTS (Round-4 hardening): app/error.tsx catches errors thrown by
 * route segments BELOW the root layout — but if app/layout.tsx itself (or
 * app/providers.tsx during render) throws, there is no boundary left and the
 * user gets the framework's unstyled crash screen. global-error.tsx is the
 * Next.js-designated catch-all for exactly that case.
 *
 * WHY IT RENDERS ITS OWN <html>/<body>: when this boundary activates, the
 * root layout is gone — Next.js mandates that global-error supply the full
 * document shell. We import globals.css ourselves for the same reason (the
 * root layout that normally imports it never rendered).
 *
 * WHY NO RouteErrorFallback / Link / shared components: keep the dependency
 * graph of the last-resort path as small as possible. If the crash came from
 * a shared module, importing it here would crash the boundary too. Plain
 * elements + an <a> (full page load — router state may be corrupt) are the
 * most robust recovery surface. Same reasoning as Next.js' own docs.
 *
 * NOTE: global-error only activates in production builds; in dev, Next.js
 * shows its error overlay instead.
 */

// WHY this import: the root layout (which normally loads the stylesheet)
// is replaced by this component, so the tokens/utilities must be loaded here
// for the Terminal Dark styling below to paint.
import "./globals.css";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    // WHY className="dark": the .dark token block in globals.css carries the
    // Terminal Dark palette; the root layout that normally sets it is gone.
    <html lang="en" className="dark">
      <body className="bg-background text-foreground antialiased">
        <main className="flex min-h-screen flex-col items-center justify-center gap-3 px-6">
          {/* Inline SVG triangle (no lucide import — see file docstring). */}
          <svg
            className="h-8 w-8 text-negative/60"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>

          {/* Named state — terminal micro-label convention. */}
          <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            Worldview — fatal error
          </p>

          <h1 className="text-base font-semibold text-foreground">
            The application failed to start
          </h1>

          <p className="max-w-[360px] text-center text-[11px] text-muted-foreground">
            An unrecoverable error occurred while rendering the application
            shell. Try again, or reload the page if the problem persists.
          </p>

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={reset}
              className="h-7 rounded-[2px] border border-border bg-card px-3 text-[11px] text-foreground transition-colors hover:bg-muted"
            >
              Try again
            </button>
            {/* WHY <a> not <Link>: forces a full document reload — the client
                router's in-memory state may be the thing that crashed, so a
                soft navigation could re-throw instantly. The eslint disable is
                deliberate and scoped: this is the ONLY place in the app where
                an <a> to an internal page is correct. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a
              href="/"
              className="h-7 rounded-[2px] border border-border px-3 text-[11px] leading-7 text-muted-foreground transition-colors hover:text-foreground"
            >
              Reload Worldview
            </a>
          </div>

          {/* Digest — small mono debugging handle (see RouteErrorFallback). */}
          {error.digest && (
            <p className="pt-2 font-mono text-[9px] text-muted-foreground/50">
              digest: {error.digest}
            </p>
          )}
        </main>
      </body>
    </html>
  );
}
