/**
 * useInstrumentBundle.ts
 * WHY THIS EXISTS: the instrument detail page composes header, AI brief and
 *   multiple tabs that all need the same page-bundle payload. Fetching it
 *   once at page level via a shared TanStack Query cache entry avoids a
 *   sub-component waterfall.
 * WHO USES IT: InstrumentPageClient (page orchestrator).
 * DATA SOURCE: GET /v1/instruments/{id}/page-bundle (S9 composite).
 * DESIGN REFERENCE: PRD-0088 §6.3, PLAN-0090 T-A-03.
 */

"use client";
// WHY "use client": useQuery needs the QueryClient React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway, GatewayError } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

// WHY staleTime 5min: bundle holds slow-moving data (fundamentals, top news).
// Fresh enough during market hours, long enough to avoid tab-switch refetches.
// WHY !!entityId gate: empty id during route hydration would 404 on S9.
export function useInstrumentBundle(entityId: string) {
  const token = useAccessToken();
  return useQuery({
    queryKey: qk.instruments.pageBundle(entityId),
    queryFn: () => createGateway(token).getInstrumentPageBundle(entityId),
    staleTime: 5 * 60 * 1000,
    enabled: !!entityId,
    // ── Round-4 hardening (item 1c): 4xx-aware retry policy ────────────────
    // WHY: a bogus ticker in the URL (e.g. /instruments/ZZZZBOGUS) makes S9
    // return 404 deterministically. TanStack's default policy retries 3×
    // with exponential backoff, so the analyst stared at a skeleton for
    // ~7 seconds before the query even settled into its error state. Client
    // errors (4xx) are NOT transient — retrying cannot succeed — so we fail
    // fast and let InstrumentPageClient render <InstrumentNotFound/>
    // immediately. Server/network errors (5xx, status 0) keep one retry:
    // a single S9 hiccup shouldn't strand the page on the error screen.
    retry: (failureCount, error) => {
      if (error instanceof GatewayError && error.status >= 400 && error.status < 500) {
        return false; // deterministic client error — never retry
      }
      return failureCount < 1; // transient class — one retry, then surface
    },
  });
}
