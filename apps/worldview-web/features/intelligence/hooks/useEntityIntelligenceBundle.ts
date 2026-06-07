/**
 * features/intelligence/hooks/useEntityIntelligenceBundle.ts — PLAN-0099 H
 *
 * WHY THIS HOOK EXISTS (Agent D audit I1 + I2):
 *   - The Intelligence tab previously fired 5 independent gateway calls on
 *     mount: entity detail, instrument brief, depth=2 graph (GraphColumn),
 *     depth=1 graph (ContextPanel — REDUNDANT), paths, and intelligence
 *     summary. Each call is its own TLS handshake / auth round-trip; the
 *     tab was wave-serialized by the slowest leg.
 *   - This hook calls a single composite endpoint (GET
 *     /v1/entities/{id}/intelligence-bundle) that fans out server-side via
 *     asyncio.gather. After the bundle resolves, an effect HYDRATES each
 *     per-widget TanStack cache via setQueryData so the child queries (in
 *     ContextPanel, GraphColumn, PathInsightsBlock, useEntityIntelligence)
 *     see the data as already-fetched and skip their own initial fetches.
 *
 * CRITICAL: the depth=2 graph leg is seeded under the EXACT cache key the
 * GraphColumn reads (qk.instruments.entityGraph(entityId, 2)). Without that
 * key match TanStack treats the cache as empty and the bundle is wasted.
 *
 * USAGE:
 *   const { isLoading } = useEntityIntelligenceBundle(entityId);
 *   // ContextPanel / GraphColumn / PathInsightsBlock all read from the
 *   // hydrated caches — no further wiring needed.
 *
 * MIRRORS the DashboardBundleHydrator pattern (components/dashboard/
 * DashboardBundleHydrator.tsx) — same setQueryData-in-useEffect approach,
 * same exact-key requirement, same fail-soft per-leg semantics.
 */

"use client";
// WHY "use client": useQuery + useEffect + useQueryClient all require browser
// runtime. Only Client Components may import this hook.

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import type { EntityIntelligenceBundleResponse } from "@/lib/api/knowledge-graph";

/** Cache key for the bundle fetch itself.  Not read by children; only used
 *  to dedupe parallel mounts of the hook (e.g. tab pre-rendered + visible). */
const bundleKey = (entityId: string) =>
  ["entity-intelligence-bundle", entityId] as const;

/**
 * useEntityIntelligenceBundle — fetches the H bundle once + hydrates per-widget caches.
 *
 * @param entityId The KG entity_id for the instrument page's primary entity.
 *                 The hook stays disabled until both this and a token are present.
 *
 * Returns the raw TanStack query result so callers can render a top-level
 * skeleton during cold start if they want. Most callers will not use the
 * data directly — they rely on the cache hydration side-effect.
 */
export function useEntityIntelligenceBundle(entityId: string) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  const query = useQuery<EntityIntelligenceBundleResponse>({
    queryKey: bundleKey(entityId),
    queryFn: () => createGateway(accessToken).getEntityIntelligenceBundle(entityId),
    // WHY enabled gate: we MUST have a token (apiFetch will throw GatewayError
    // without one) and a real entityId (UUID would 422 from S9 otherwise).
    enabled: !!accessToken && !!entityId,
    // WHY 5min staleTime: matches the longest leg's underlying cache (paths is
    // backend-cached for 5min; intelligence for 60s). Refetching faster than
    // the backend cache TTL just returns the same data.
    staleTime: 5 * 60 * 1000,
    // WHY refetchOnWindowFocus false: the bundle is large; tab switching should
    // not trigger a 5-leg re-fetch. Individual widgets that need live data
    // (e.g. brief regenerate button) invalidate their own targeted keys.
    refetchOnWindowFocus: false,
    // WHY no retry: the route degrades each leg to null on failure — a retry
    // at the wrapper level would re-fan out 5 already-failed legs needlessly.
    retry: 0,
  });

  const bundle = query.data ?? null;

  useEffect(() => {
    if (!bundle) return;

    // ── Hydrate per-widget caches ────────────────────────────────────────
    // WHY each setQueryData uses the EXACT key the widget reads:
    // TanStack matches cache entries by structural key equality. If the
    // hydrated key differs by even one element from the widget's queryKey,
    // the widget treats the cache as empty and fires its own initial fetch
    // — defeating the bundle entirely.

    // ContextPanel's entityDetailQuery uses ["entity-detail", entityId].
    if (bundle.detail !== null) {
      queryClient.setQueryData(["entity-detail", entityId], bundle.detail);
    }

    // GraphColumn's brief query uses qk.instruments.brief(entityId).
    // WHY the same key as the per-instrument brief: the Intelligence tab and
    // the Quote tab both render the same AI brief; sharing the cache slot
    // means the second tab sees the data already loaded.
    if (bundle.brief !== null) {
      queryClient.setQueryData(qk.instruments.brief(entityId), bundle.brief);
    }

    // CRITICAL (I1): GraphColumn's graph query uses
    // qk.instruments.entityGraph(entityId, 2). We seed depth=2 here so the
    // GraphColumn does NOT fire its own initial fetch. ContextPanel no
    // longer fires a separate depth=1 fetch — it derives depth-1 neighbours
    // from this same depth=2 graph (filter to edges incident on the root).
    if (bundle.graph_d2 !== null) {
      queryClient.setQueryData(
        qk.instruments.entityGraph(entityId, 2),
        bundle.graph_d2,
      );
    }

    // PathInsightsBlock uses useEntityPaths which keys on
    // ["entity-paths", entityId, filters] with filters defaulting to {}.
    // We seed the empty-filters slot so the cold-start render sees data.
    if (bundle.paths !== null) {
      queryClient.setQueryData(["entity-paths", entityId, {}], bundle.paths);
    }

    // useEntityIntelligence keys on ["entity-intelligence", entityId].
    // Used by ContextPanel's health badge + the intelligence sidebar.
    if (bundle.intelligence_summary !== null) {
      queryClient.setQueryData(
        ["entity-intelligence", entityId],
        bundle.intelligence_summary,
      );
    }
    // WHY entityId in deps: changing entity (e.g. navigating between
    // instrument pages without unmount) must re-hydrate under the new id.
  }, [bundle, entityId, queryClient]);

  return query;
}
