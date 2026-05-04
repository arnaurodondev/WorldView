/**
 * sentry.edge.config.ts — Sentry SDK initialisation for the Edge runtime.
 *
 * WHY THIS EXISTS:
 * Next.js 15 has three runtimes: browser, Node.js server, and Edge.
 * The Edge runtime runs middleware and any route handler/page that uses
 * `export const runtime = "edge"`. It has a reduced API surface — no Node
 * built-ins, no full V8 — so a separate minimal Sentry config is required.
 *
 * In this project, Edge runtime usage is minimal (only middleware.ts runs on
 * Edge). The config mirrors the server config but skips Node-specific options.
 *
 * This file is imported by instrumentation.ts when NEXT_RUNTIME === "edge".
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  // Same DSN as client/server — one Sentry project captures all runtimes.
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN ?? "",

  // Tag events by environment (development / staging / production).
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "development",

  // Tracing disabled — Tempo handles distributed tracing.
  tracesSampleRate: 0,

  // No PII collection at the SDK layer.
  sendDefaultPii: false,

  // WHY no beforeSend here: Edge runtime cannot import lib/sentry/strip-pii.ts
  // because that file uses TextEncoder and crypto.subtle — both available in
  // Edge, but the dynamic import path via @/ alias may not resolve in the
  // Edge bundler's restricted module graph. Since middleware.ts (the main
  // Edge file) does not handle auth headers or user data directly, the risk
  // of PII leakage from Edge events is low. Add beforeSend here if Edge
  // routes are added that process user-identifiable data.
});
