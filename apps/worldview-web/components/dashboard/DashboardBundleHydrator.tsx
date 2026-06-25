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
// Round 1 foundation: the bundle's top_gainers/top_losers legs carry the RAW
// S9/S3 envelope ({results: [...]}), but every widget cache expects the
// TRANSFORMED {movers: Mover[]} shape produced by getTopMovers(). Seeding the
// raw shape made widgets read `undefined.movers` → empty lists on cold start.
// The shared transform keeps the hydrated cache byte-compatible with what the
// widget's own queryFn would produce.
import {
  transformTopMoversResponse,
  type RawTopMoversResponse,
} from "@/lib/api/dashboard";

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

    // Top movers (gainers/losers) — Round 1 foundation fix.
    //
    // TWO bugs lived here before:
    //   1. SHAPE: the legs are the RAW S9 envelope ({results: [{instrument_id,
    //      ticker, name, period_return_pct}]}) while the consumers expect the
    //      TRANSFORMED {movers: Mover[], type} from getTopMovers(). We now run
    //      the exact same transform the queryFn applies.
    //   2. KEYS: only qk.dashboard.topMovers(...) was hydrated, but the legacy
    //      PreMarketMoversWidget reads ["dashboard-top-movers-<type>", "1D"].
    //      We seed BOTH key families so whichever movers widget is mounted
    //      renders from cache. (TopMovers — the Round 1 MARKET tab widget —
    //      reads the qk key; the legacy flat keys keep PreMarketMoversWidget
    //      working anywhere it is still mounted.)
    if (bundle.top_gainers !== null) {
      const gainers = transformTopMoversResponse(
        bundle.top_gainers as RawTopMoversResponse,
        "gainers",
      );
      queryClient.setQueryData(
        qk.dashboard.topMovers({ type: "gainers", limit: 10, period: "1D" }),
        gainers,
      );
      queryClient.setQueryData(["dashboard-top-movers-gainers", "1D"], gainers);
    }
    if (bundle.top_losers !== null) {
      const losers = transformTopMoversResponse(
        bundle.top_losers as RawTopMoversResponse,
        "losers",
      );
      queryClient.setQueryData(
        qk.dashboard.topMovers({ type: "losers", limit: 10, period: "1D" }),
        losers,
      );
      queryClient.setQueryData(["dashboard-top-movers-losers", "1D"], losers);
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
