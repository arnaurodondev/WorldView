/**
 * instrumentation.ts — Next.js 15 instrumentation hook entry point.
 *
 * WHY THIS FILE EXISTS:
 * Next.js 15 introduced a stable `instrumentation.ts` convention: when this
 * file exists at the project root, Next.js calls `register()` once per server
 * process start (not per request). It is the canonical place for one-time
 * server-side setup like Sentry initialisation.
 *
 * WHY NOT inline in app/layout.tsx or pages/_app.tsx:
 * Those files are executed per-render or per-request. Sentry.init() must be
 * called exactly once per process — not once per render. `instrumentation.ts`
 * guarantees the once-per-process semantics.
 *
 * WHY NEXT_RUNTIME guards:
 * Next.js bundles this file separately for Node.js and Edge runtimes. Each
 * runtime has a different import surface (e.g. Node can use `crypto` built-ins;
 * Edge cannot). Dynamic imports inside the `if` blocks ensure the correct
 * runtime-specific config is loaded without the other runtime's modules
 * leaking in and causing bundler errors.
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    // Node.js server runtime — API Route Handlers, SSR pages, server actions.
    // This import triggers Sentry.init() for the Node process.
    await import("./sentry.server.config");
  }

  if (process.env.NEXT_RUNTIME === "edge") {
    // Edge runtime — middleware.ts and any route handler with `runtime = "edge"`.
    // Uses a minimal Sentry config (no Node built-ins).
    await import("./sentry.edge.config");
  }

  // WHY no browser case here: the client Sentry config (sentry.client.config.ts)
  // is injected into every browser JS bundle by the Sentry webpack plugin
  // (configured in next.config.ts via withSentryConfig). That injection happens
  // at build time — no runtime import needed here.
}
