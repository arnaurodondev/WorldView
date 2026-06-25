"use client";
/**
 * app/(app)/error.tsx — (app) route-group fallback error boundary
 *
 * WHY THIS EXISTS (Round-4 hardening): most authenticated routes ship their
 * own error.tsx (dashboard, screener, news, alerts, …) but several segments
 * had NO boundary (indices, prediction-markets, workspace sub-segments,
 * future routes). Without one, an unhandled render error in those segments
 * bubbles all the way to app/error.tsx — which renders OUTSIDE the (app)
 * shell, so the user loses the TopBar/sidebar entirely. This group-level
 * boundary is the safety net: it catches anything a per-route boundary
 * didn't, while keeping the terminal chrome ((app)/layout.tsx) intact.
 *
 * BOUNDARY ORDER (nearest wins):
 *   per-route error.tsx → THIS file → app/error.tsx → app/global-error.tsx
 *
 * Note: errors thrown by (app)/layout.tsx itself are NOT caught here —
 * error.tsx only wraps the layout's children. Those fall through to
 * app/error.tsx by design.
 *
 * UI: shared RouteErrorFallback primitive (DESIGN_SYSTEM.md §6.7.1) — named
 * state, warning icon, "Try again" via reset(), digest shown small.
 */

import { RouteErrorFallback } from "@/components/primitives/RouteErrorFallback";

export default function AppGroupError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // WHY label "APP": this boundary covers any (app) segment that lacks its
  // own error.tsx, so the label names the group, not a specific surface.
  return <RouteErrorFallback error={error} reset={reset} routeLabel="App" />;
}
