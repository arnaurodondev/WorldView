/**
 * lib/api/prediction-markets.ts — Polymarket prediction-market list/categories/history.
 */

import type {
  PredictionMarket,
  PredictionMarketsResponse,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createPredictionMarketsApi(t: string | undefined) {
  return {
    /**
     * getPredictionMarkets — open/live prediction market odds
     *
     * WHY transform: S3 returns `PredictionMarketsListResponse` = `{items: [...], total, limit, offset}`
     * where each item is a `PredictionMarketSummaryResponse` with fields like `question` (not `title`),
     * `outcomes` array (not `yes_probability`/`no_probability`), `resolution_status` (not `status`),
     * and `volume_24h` (not `volume_usd`). The frontend expects `PredictionMarketsResponse` =
     * `{markets: PredictionMarket[], total}` with the simpler yes/no probability model.
     */
    async getPredictionMarkets(
      params: { status?: string; limit?: number } = {},
    ): Promise<PredictionMarketsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();

      // S3 returns PredictionMarketsListResponse with `items` (not `markets`)
      const raw = await apiFetch<{
        items: Array<{
          market_id: string;
          question: string;
          outcomes: Array<{ name: string; token_id: string; price: number }>;
          volume_24h: number | null;
          close_time: string | null;
          resolution_status: string;
          resolved_answer: string | null;
          updated_at: string;
          // WHY market_slug: added in B-2 (migration 009); may be null for markets
          // ingested before the field was added. Null → empty URL → search fallback.
          market_slug: string | null;
        }>;
        total: number;
        limit: number;
        offset: number;
      }>(`/v1/signals/prediction-markets${qs ? `?${qs}` : ""}`, { token: t });

      // Transform S3 summary responses into frontend PredictionMarket type
      const markets: PredictionMarket[] = (raw.items ?? []).map((m) => {
        // WHY outcome extraction: S3 stores outcomes as an array of {name, token_id, price}
        // where price is the implied probability (0.0–1.0). The frontend expects simple
        // yes_probability/no_probability fields. We look for "Yes"/"No" outcomes by name.
        const yesOutcome = m.outcomes.find((o) => o.name.toLowerCase() === "yes");
        const noOutcome = m.outcomes.find((o) => o.name.toLowerCase() === "no");

        return {
          market_id: m.market_id,
          title: m.question, // S3 calls it "question", frontend calls it "title"
          description: "", // Summary response doesn't include description (detail endpoint does)
          yes_probability: yesOutcome?.price ?? 0,
          no_probability: noOutcome?.price ?? 1 - (yesOutcome?.price ?? 0.5),
          volume_usd: m.volume_24h ?? 0, // S3 uses volume_24h, frontend uses volume_usd
          // WHY map resolution_status → status: S3 uses "open"/"resolved"/"cancelled",
          // frontend expects "open"/"closed"/"resolved". Map "cancelled" → "closed".
          status: (m.resolution_status === "cancelled"
            ? "closed"
            : m.resolution_status) as "open" | "closed" | "resolved",
          resolution_date: m.close_time,
          entity_ids: [], // Not available in summary response — would need entity linking
          tickers: [], // Same — summary doesn't include ticker associations
          source: "polymarket" as const, // Currently only Polymarket is integrated (PRD-0019)
          // WHY a search URL by default (density bundle 2026-05-09): the previous
          // ``/event/{slug}`` pattern returned 404 for many markets — Polymarket's
          // canonical URLs distinguish ``/event/`` (grouped market) from
          // ``/market/`` (single binary), and the ``slug`` field on the Gamma
          // ``markets`` payload does NOT reliably match either path. The most
          // robust user-facing fallback is the search page, which always resolves
          // to a working result for any title. We empty the ``url`` so the widget's
          // own ``url -> slug -> search`` ladder still runs and prefers the search.
          url: "",
          // WHY pass market_slug through: PredictionMarketsWidget (Wave A-4) builds
          // the URL client-side using market_slug as a second fallback after url.
          // Preserving it avoids re-fetching when url is empty.
          market_slug: m.market_slug,
          updated_at: m.updated_at,
        };
      });

      return { markets, total: raw.total };
    },

    /**
     * getPredictionMarketCategories — per-category counts of currently-open markets
     *
     * PLAN-0053 T-C-3-05. Powers the dashboard filter pills (e.g.
     * `[All 87] [Macro 12] [Politics 8]`) and the empty-state explainer
     * ("No markets in this category right now (only X macro markets available)").
     *
     * WHY a separate endpoint (instead of computing client-side from the list):
     * the list endpoint is paginated + filtered; the counts must reflect the
     * FULL universe of open markets so the pills aren't empty when the user
     * has applied a filter. A single GROUP BY query on the backend is cheap
     * and stays out-of-band of the list query's pagination.
     *
     * Response is forward-compatible: a new Polymarket category lights up the
     * UI automatically without a code change (the pill row renders any
     * category the API returns, mapping known buckets to localized labels and
     * passing unknowns through as-is).
     */
    async getPredictionMarketCategories(): Promise<{
      items: Array<{ category: string | null; count: number }>;
      total: number;
    }> {
      return apiFetch<{
        items: Array<{ category: string | null; count: number }>;
        total: number;
      }>(`/v1/signals/prediction-markets/categories`, { token: t });
    },

    /**
     * getPredictionMarketHistory — time-series of yes-probability snapshots
     *
     * WHY THIS EXISTS (PLAN-0048 D-2): the dashboard PredictionMarketsWidget
     * needs (a) a 24h Δ pp computed from the most recent two snapshots and
     * (b) a 7-day mini sparkline. Both come from the existing S9 → S3 history
     * proxy at `/v1/signals/prediction-markets/{id}/history`.
     *
     * WHY days-only API surface: callers use day windows (1d for delta,
     * 7d for sparkline). We translate `days` to a `from=now-Nd` query param
     * so the caller doesn't have to format ISO dates.
     *
     * WHY shaped: the S3 response uses `outcomes_prices: { Yes, No }` per
     * snapshot. We extract `yes_probability` for the dashboard widget so
     * the consumer doesn't need to re-implement the same lookup logic.
     */
    async getPredictionMarketHistory(
      marketId: string,
      days = 7,
    ): Promise<{
      market_id: string;
      points: Array<{ snapshot_at: string; yes_probability: number }>;
    }> {
      // Compute the `from` timestamp client-side. WHY ISO + Z: FastAPI's
      // `datetime` query param expects ISO 8601; the trailing Z keeps it UTC.
      const fromIso = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
      const qs = new URLSearchParams({ from: fromIso, limit: "200" }).toString();

      const raw = await apiFetch<{
        market_id: string;
        snapshots: Array<{
          snapshot_at: string;
          outcomes_prices: Record<string, number>;
          volume_24h: number | null;
        }>;
      }>(
        `/v1/signals/prediction-markets/${encodeURIComponent(marketId)}/history?${qs}`,
        { token: t },
      );

      // Map each snapshot to a simple {snapshot_at, yes_probability} pair.
      // WHY default 0: if the outcome key is missing (rare — early ingestion
      // gap), 0 is safer than NaN for sparkline rendering. The chart still
      // looks reasonable; the trader sees the gap.
      const points = (raw.snapshots ?? []).map((s) => ({
        snapshot_at: s.snapshot_at,
        yes_probability: s.outcomes_prices?.Yes ?? s.outcomes_prices?.yes ?? 0,
      }));

      // S3 returns snapshots ORDER BY snapshot_at DESC. The sparkline + delta
      // logic below expects ascending (oldest → newest) order so the path
      // moves left-to-right in time. Reverse here once instead of in every
      // consumer.
      points.reverse();

      return { market_id: raw.market_id, points };
    },
  };
}
