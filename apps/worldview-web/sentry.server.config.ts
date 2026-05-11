/**
 * sentry.server.config.ts — Sentry SDK initialisation for the Node.js server runtime.
 *
 * WHY SEPARATE FROM CLIENT CONFIG:
 * Next.js 15 runs two distinct runtimes: the browser bundle (loaded by users'
 * browsers) and the Node.js server (runs SSR, API Route Handlers, middleware).
 * Each runtime needs its own Sentry init because:
 *   1. The DSN env var names differ (NEXT_PUBLIC_ for client, bare for server)
 *   2. Instrumentation hooks differ (server can auto-capture fetch spans; browser can't)
 *   3. PII exposure vectors differ (server may see auth cookies; browser never does)
 *
 * This file is imported by instrumentation.ts (the Next.js 15 instrumentation
 * hook entry point) when NEXT_RUNTIME === "nodejs".
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

import * as Sentry from "@sentry/nextjs";
import { type SentryEventShape, stripPii } from "@/lib/sentry/strip-pii";

Sentry.init({
  // WHY no NEXT_PUBLIC_ prefix: server-side env vars are NOT embedded in the
  // browser bundle. Process.env is read at request time from the running
  // Node process — safe for non-public values (not that the DSN is secret,
  // but consistency with server env var conventions matters).
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN ?? "",

  // Environment label shown in the Sentry project dashboard.
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "development",

  // Performance tracing disabled — OpenTelemetry + Tempo already own this.
  // Sentry free tier: 5K events/month reserved for error capture only.
  tracesSampleRate: 0,

  // Full stack traces on all events, not just exceptions.
  attachStacktrace: true,

  // Prevent the SDK from auto-collecting PII like cookies and user IPs.
  // Belt-and-suspenders: beforeSend also strips these, but the SDK flag
  // prevents collection before beforeSend fires.
  sendDefaultPii: false,

  // PII guard: same function as the client config, imported from a shared
  // utility so tests can verify it without initialising the Sentry SDK.
  // WHY @ts-expect-error: same nominal/structural type mismatch as the client
  // config — SentryEventShape is structurally identical to Sentry v10's
  // ErrorEvent at runtime; the cast is safe.
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-expect-error: structurally compatible at runtime; see above
  beforeSend: (event) => stripPii(event as unknown as SentryEventShape),
});
