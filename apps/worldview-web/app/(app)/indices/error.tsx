"use client";
/**
 * app/(app)/indices/error.tsx — Indices route error boundary
 *
 * WHY THIS EXISTS (Round-4 hardening): indices was the only first-level (app)
 * route without an error.tsx while every sibling (news, alerts, watchlists,
 * search, settings, …) had one. A render error in /indices/[ticker] (e.g. a
 * malformed OHLCV payload crashing the inline chart) would have bubbled to
 * the group-level boundary with the generic "APP" label; this file names the
 * surface so the failure is identifiable at a glance / in a screenshot.
 *
 * UI: shared RouteErrorFallback primitive — see DESIGN_SYSTEM.md §6.7.1.
 */

import { RouteErrorFallback } from "@/components/primitives/RouteErrorFallback";

export default function IndicesError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <RouteErrorFallback error={error} reset={reset} routeLabel="Indices" />
  );
}
