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
import { createGateway } from "@/lib/gateway";
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
  });
}
