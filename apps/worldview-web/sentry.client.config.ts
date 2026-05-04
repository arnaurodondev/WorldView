/**
 * sentry.client.config.ts — Sentry SDK initialisation for the browser runtime.
 *
 * WHY A SEPARATE FILE (not inline in providers.tsx):
 * Next.js 15 + @sentry/nextjs requires this exact filename. The Sentry webpack
 * plugin (wired in next.config.ts via withSentryConfig) automatically injects
 * an import of this file into every browser JS bundle chunk. That means Sentry
 * is initialised BEFORE any React component mounts — unhandled promise rejections
 * and early JS errors are captured even before the React tree hydrates.
 *
 * This file runs IN THE BROWSER only. Do NOT import Node-only modules here.
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

import * as Sentry from "@sentry/nextjs";
import { type SentryEventShape, stripPii } from "@/lib/sentry/strip-pii";

// WHY NO REPLAY:
// Session Replay records mouse movement, clicks, and DOM snapshots — a privacy
// risk in a financial terminal where Sam's research actions are sensitive.
// MVP default: replay off. Can be enabled post-launch with explicit opt-in.
const REPLAYS_SESSION_SAMPLE_RATE = 0;
const REPLAYS_ON_ERROR_SAMPLE_RATE = 0;

// WHY TRACES_SAMPLE_RATE = 0:
// Distributed tracing is already handled by OpenTelemetry → Tempo (PLAN-0054).
// Double-billing with Sentry performance tracing adds cost with zero extra signal.
// The Sentry free tier's 5K events/month budget is reserved for error events only.
const TRACES_SAMPLE_RATE = 0;

Sentry.init({
  // DSN: Data Source Name — tells the SDK where to send events.
  // NEXT_PUBLIC_ prefix means it is baked into the JS bundle at build time.
  // WHY default "": an empty DSN puts the SDK into disabled mode — no network
  // calls, no errors, behaves as a no-op. This keeps dev/CI clean without
  // needing SENTRY_ENABLED logic in the frontend (handled by empty DSN).
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN ?? "",

  // Environment tag: shown in the Sentry dashboard to separate prod from staging.
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "development",

  // Performance tracing disabled — Tempo already owns distributed traces.
  tracesSampleRate: TRACES_SAMPLE_RATE,

  // Replay disabled — privacy-conservative MVP default.
  replaysSessionSampleRate: REPLAYS_SESSION_SAMPLE_RATE,
  replaysOnErrorSampleRate: REPLAYS_ON_ERROR_SAMPLE_RATE,

  // Attach stacktrace to all events (not just exceptions).
  // WHY: console.error calls become actionable with a stack frame attached.
  // Disabled by default in Sentry — we enable it deliberately here.
  attachStacktrace: true,

  // Never send raw request bodies to Sentry.
  // This is belt-and-suspenders: beforeSend also drops `data`, but this
  // SDK flag prevents collection before beforeSend even fires.
  sendDefaultPii: false,

  // PII guard: runs on every event before it leaves the process.
  // Strips auth headers, cookies, query strings, instrument slugs in URLs,
  // and hashes user.email. See lib/sentry/strip-pii.ts for full spec.
  // WHY @ts-expect-error: Sentry v10 types beforeSend to return
  // `ErrorEvent | null` but `stripPii` returns `Promise<SentryEventShape | null>`.
  // SentryEventShape is structurally identical to ErrorEvent at runtime; the
  // nominal type mismatch is an artefact of Sentry v10's more specific typing.
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-expect-error: structurally compatible at runtime; see above
  beforeSend: (event) => stripPii(event as unknown as SentryEventShape),
});
