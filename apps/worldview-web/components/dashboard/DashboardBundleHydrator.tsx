/**
 * components/dashboard/DashboardBundleHydrator.tsx — F-2 cache hydrator
 *
 * WHY THIS COMPONENT EXISTS (F-2):
 * The dashboard page is a Next.js Server Component (no "use client") so its
 * shell is SSR'd without JS. Hooks cannot run in Server Components, so this
 * thin client wrapper:
 *   1. Fires useDashboardBundle() to fetch the F-2 composite in one round-trip.
 *   2. Hydrates the per-widget TanStack query caches via setQueryData so child
 *      widgets render from cache WITHOUT firing their own initial fetches.
 *
 * The page already mounts DashboardSnapshotPrefetcher (PLAN-0070 C-2) which
 * warms qk.dashboard.snapshot() — but that key is NEVER read by the widgets
 * (they each use their own keys), so the snapshot does not actually eliminate
 * wave-serialization. THIS hydrator does, by writing into the EXACT keys the
 * widgets read.
 *
 * WHY hydrate inside useEffect (not synchronously inside the queryFn): the
 * setQueryData calls must fire AFTER the bundle resolves but BEFORE any child
 * widget queryFn runs. TanStack Query batches queries within the same tick, so
 * a useEffect with the bundle in its dep array is the correct seam — the
 * effect fires after the bundle is in the cache and before the next render
 * pass kicks off child queryFns.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (invisible, renders null).
 * DATA SOURCE: S9 GET /v1/dashboard/bundle (F-2).
 */

"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import { useDashboardBundle } from "@/features/dashboard/hooks/useDashboardBundle";

export function DashboardBundleHydrator() {
  const { data: bundle } = useDashboardBundle();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!bundle) return;

    // ── Hydrate per-widget caches ────────────────────────────────────────
    // WHY each setQueryData uses the EXACT key the widget reads:
    // TanStack matches cache entries by structural key equality. If the
    // hydrated key differs by even one element from the widget's queryKey,
    // the widget treats the cache as empty and fires its own initial fetch
    // — defeating the bundle entirely.

    // Morning brief widget reads ["morning-brief"] (legacy flat key) —
    // see components/dashboard/MorningBriefCard.tsx:157.
    if (bundle.brief !== null) {
      queryClient.setQueryData(["morning-brief"], bundle.brief);
      // Also hydrate the qk-factory key so any future migration to qk picks
      // up the same data without an extra fetch.
      queryClient.setQueryData(qk.dashboard.morningBrief(), bundle.brief);
    }

    // Recent alerts widget reads ["alerts-pending"] — see RecentAlerts.tsx:62.
    if (bundle.recent_alerts !== null) {
      queryClient.setQueryData(["alerts-pending"], bundle.recent_alerts);
    }

    // Sector heatmap widget reads ["sector-heatmap-widget", period] — the
    // bundle always uses period="1D" so we hydrate only that variant.
    if (bundle.sector_heatmap !== null) {
      queryClient.setQueryData(["sector-heatmap-widget", "1D"], bundle.sector_heatmap);
      // Also hydrate the qk-factory key (no period dimension there).
      queryClient.setQueryData(qk.dashboard.marketHeatmap(), bundle.sector_heatmap);
    }

    // Top movers (gainers/losers) — qk.dashboard.topMovers takes optional
    // params. The dashboard PreMarketMovers widget calls with params
    // matching {type, limit, period}; we hydrate the two 1D variants the
    // bundle covers.
    if (bundle.top_gainers !== null) {
      queryClient.setQueryData(
        qk.dashboard.topMovers({ type: "gainers", limit: 10, period: "1D" }),
        bundle.top_gainers,
      );
    }
    if (bundle.top_losers !== null) {
      queryClient.setQueryData(
        qk.dashboard.topMovers({ type: "losers", limit: 10, period: "1D" }),
        bundle.top_losers,
      );
    }

    // Portfolios list — PortfolioSummary widget reads qk.portfolios.list()
    // (PortfolioSummary.tsx:58). Hydrating this lets the portfolio widget
    // skip the initial /v1/portfolios round-trip on cold start.
    //
    // WHY transform: the bundle leg calls S1 via the S9 proxy, which returns the
    // raw paginated envelope {items: [{id, ...}], total, limit, offset}. But
    // getPortfolios() (lib/api/portfolios.ts) transforms that into Portfolio[]
    // (renaming `id` → `portfolio_id` and mapping fields). We must apply the same
    // transform here so the seeded cache is structurally identical to what the
    // widget's own queryFn would produce — otherwise `.find()` fails on an object
    // instead of an array ("Y.find is not a function" runtime error, PLAN-0099 W4).
    if (bundle.portfolios !== null) {
      const raw = bundle.portfolios as { items?: Array<{
        id: string; name: string; currency: string; owner_id: string;
        created_at: string; kind?: "manual" | "brokerage" | "root";
      }> } | null;
      const portfolioList = (raw?.items ?? []).map((p) => ({
        portfolio_id: p.id,
        name: p.name,
        currency: p.currency,
        owner_id: p.owner_id,
        created_at: p.created_at,
        updated_at: p.created_at,
        kind: p.kind,
      }));
      if (portfolioList.length > 0) {
        queryClient.setQueryData(qk.portfolios.list(), portfolioList);
      }
    }

    // workspace: reserved — no upstream endpoint exists yet, always null.
  }, [bundle, queryClient]);

  return null;
}
