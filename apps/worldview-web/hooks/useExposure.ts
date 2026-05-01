/**
 * hooks/useExposure.ts — shared TanStack query for portfolio exposure.
 *
 * WHY THIS EXISTS (PLAN-0052 platform-QA fix, 2026-05-01):
 * `<ExposureBreakdown>` previously owned its own inline `useQuery`. The
 * parent `<PortfolioAnalyticsSection>` couldn't know whether the child
 * was loading / empty / data-bound, so it always rendered a
 * `min-h-[200px] bg-card` panel around the child — including the empty/
 * error path where the panel collapsed visually to "half the page is
 * black on the dark background" (BP-class panel anti-pattern).
 *
 * Lifting the query into a shared hook lets BOTH the parent and the
 * child observe the same query state. The parent branches on
 * loading/empty/data to choose between (skeleton | bordered card with
 * InlineEmptyState | bg-card panel) — same pattern the equity-curve
 * cell already uses. The child consumes the hook and renders the
 * presentational tree only. Both share the same query key so TanStack
 * deduplicates the network call (a single fetch fans out to both).
 */

"use client";
// WHY "use client": uses TanStack hooks + React context (useAuth).

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";

/**
 * useExposure — fetches the portfolio exposure summary.
 *
 * Returns the standard TanStack `useQuery` result. The 30s staleTime
 * matches the prior inline query in ExposureBreakdown (the dashboard
 * refetches every 15s upstream; this panel doesn't need to be more
 * aggressive than that).
 */
export function useExposure(portfolioId: string | null | undefined) {
  const { accessToken } = useAuth();
  return useQuery({
    queryKey: ["exposure", portfolioId],
    queryFn: () =>
      createGateway(accessToken).getExposure(portfolioId as string),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 30_000,
  });
}
