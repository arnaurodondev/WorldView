/**
 * lib/api/prediction-markets.ts — Polymarket prediction-market list/categories/history.
 */

import type {
  PredictionMarket,
  PredictionMarketsResponse,
  PredictionMarketPriceHistory,
  PredictionMarketTrades,
  PredictionEventsResponse,
  EntityPredictionsResponse,
} from "@/types/api";
import { apiFetch } from "./_client";
// WHY import here: URL construction is centralised in lib/prediction-markets so
// the gateway transform, the dashboard widget, and the /prediction-markets page
// all produce IDENTICAL links. Previously this transform hardcoded `url: ""`,
// forcing the two UI files to build their own (title-search) URL — the root
// cause of the "every row links to a generic search" bug.
import { buildPolymarketUrl } from "@/lib/prediction-markets";

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
      // WHY offset added: PRD-0103 dashboard regression #3 — the standalone
      // /prediction-markets page now paginates through the universe. The
      // dashboard widget continues to pass only {status, limit:3} so it
      // shows a tight top-3 view + "View all" link.
      params: { status?: string; limit?: number; offset?: number; category?: string } = {},
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
          // WHY category: S3 has returned this since PLAN-0049 T-C-3-03 but the
          // transform silently DROPPED it — which broke every client-side
          // category filter (m.category was always undefined → zero matches).
          // Fixed 2026-06-10 (user report "filtering on predictions does not
          // work"). Nullable: rows ingested before tag-mapping have NULL.
          category: string | null;
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
          // WHY populate url here (2026-06-28 "wrong links" fix): the transform
          // used to hardcode ``url: ""`` on the theory that `/event/{slug}` 404s,
          // pushing a title-search fallback into the two UI files. But 521/525
          // stored slugs ARE valid Polymarket ``/event/`` slugs — emptying the
          // url sent EVERY row to a generic text search. buildPolymarketUrl now
          // returns the canonical ``/event/{slug}`` deep link for clean slugs and
          // gracefully falls back to the title-search URL for the ~4 malformed
          // (numeric-tail) slugs and any null/empty slug. Single source of truth.
          url: buildPolymarketUrl(m.market_slug, m.question),
          // WHY still pass market_slug through: the UI types/consumers expect it,
          // and it lets a consumer re-derive the URL defensively via the same
          // helper if it ever needs to (avoids re-fetching the payload).
          market_slug: m.market_slug,
          // 2026-06-10 fix: forward the server category. The PredictionMarket
          // type declared `category?` since PLAN-0049 but the transform never
          // populated it — /prediction-markets' category pills filtered on a
          // permanently-undefined field.
          category: m.category ?? null,
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

    /**
     * getPredictionMarketPriceHistory — per-token INTERVAL price bars (Wave E1/E2).
     *
     * WHY a SECOND history method (not overloading getPredictionMarketHistory):
     * the legacy method above returns raw probability SNAPSHOTS keyed by
     * `points:[{snapshot_at, yes_probability}]` and is consumed by the dashboard
     * widget's delta+sparkline. This method hits the SAME S9 route but with an
     * `interval` query param, which flips S3 onto the `prediction_market_prices`
     * hypertable and returns a DIFFERENT shape (`points:[{window_start_ts, price,
     * token_id, outcome_name}]`, one row per outcome token per bucket). Two
     * distinct return shapes ⇒ two methods, so neither caller has to branch on
     * the response union. The ProbabilityChart uses this one.
     *
     * @param conditionId Polymarket conditionId / S3 market_id.
     * @param interval    Bucket size: "1h" | "1d" | "1w".
     */
    async getPredictionMarketPriceHistory(
      conditionId: string,
      interval: "1h" | "1d" | "1w" = "1d",
    ): Promise<PredictionMarketPriceHistory> {
      // WHY interval on the query string: S3 only serves interval bars when the
      // param is present (omitting it returns the legacy snapshot shape). limit
      // caps the bar count so a long-lived 1h series can't return thousands of
      // rows to the browser.
      const qs = new URLSearchParams({ interval, limit: "500" }).toString();
      return apiFetch<PredictionMarketPriceHistory>(
        `/v1/signals/prediction-markets/${encodeURIComponent(conditionId)}/history?${qs}`,
        { token: t },
      );
    },

    /**
     * getPredictionMarketTrades — recent executed fills for a market (Wave E1/E2).
     *
     * Newest-first. Powers the detail Sheet's "recent flow" strip. `limit`
     * bounds the strip; the default 30 is enough to read the last flow burst
     * without paging.
     */
    async getPredictionMarketTrades(
      conditionId: string,
      limit = 30,
    ): Promise<PredictionMarketTrades> {
      const qs = new URLSearchParams({ limit: String(limit) }).toString();
      return apiFetch<PredictionMarketTrades>(
        `/v1/signals/prediction-markets/${encodeURIComponent(conditionId)}/trades?${qs}`,
        { token: t },
      );
    },

    /**
     * getPredictionEvents — Polymarket "event" groups (Wave E1/E2).
     *
     * Each item is a group header (name + category + market_count). NOTE: the
     * list response does NOT enumerate the child markets — S3 has no
     * event_id→markets edge on the wire yet — so the Events section renders the
     * group metadata and cannot (honestly) nest the individual market rows.
     */
    async getPredictionEvents(
      params: { limit?: number; offset?: number } = {},
    ): Promise<PredictionEventsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<PredictionEventsResponse>(
        `/v1/signals/prediction-markets/events${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },

    /**
     * getEntityPredictions — prediction markets that reference an entity (Wave E1).
     *
     * Backed by S7 GET /v1/entities/{id}/predictions. Each item carries a
     * `polarity` (bullish/bearish/neutral) that is the directional read FOR the
     * entity. An entity with no linked markets returns `{items:[], total:0}` —
     * never a 404 (absence of links is a valid state).
     */
    async getEntityPredictions(
      entityId: string,
      params: { limit?: number; offset?: number } = {},
    ): Promise<EntityPredictionsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<EntityPredictionsResponse>(
        `/v1/entities/${encodeURIComponent(entityId)}/predictions${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },
  };
}
