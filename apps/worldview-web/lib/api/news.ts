/**
 * lib/api/news.ts — News feeds (top-ranked, per-entity, legacy relevant).
 *
 * Backed by S6 NLP-pipeline (PRD-0026 ranking) for `/v1/news/top` and
 * `/v1/news/entity/*`; S5 content-store still serves `/v1/news/relevant`.
 */

import type {
  NewsResponse,
  RankedNewsResponse,
  TopNewsParams,
  EntityNewsParams,
} from "@/types/api";
import { apiFetch } from "./_client";

export function createNewsApi(t: string | undefined) {
  return {
    /**
     * getTopNews — ranked news feed by composite relevance/impact score (PRD-0026)
     * Used by: Dashboard WatchlistNews, Alerts/News page → Top Today tab
     *
     * WHY no auth: news/top is a public endpoint — no personal data involved.
     * WHY RankedNewsResponse: S6 NLP Pipeline (not S5 Content Store) now serves
     * this endpoint, returning the richer RankedArticle shape with multi-window
     * price impact scores and LLM relevance scores. Proxy retargeted in Wave 7.
     *
     * @param params - TopNewsParams (hours, limit, offset, min_display_score, routing_tier)
     */
    getTopNews(params: TopNewsParams = {}): Promise<RankedNewsResponse> {
      const qs = new URLSearchParams(
        // WHY filter null/undefined: URLSearchParams(undefined) → "undefined" string.
        // This filter ensures only explicitly set params appear in the query string.
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<RankedNewsResponse>(`/v1/news/top${qs ? `?${qs}` : ""}`);
    },

    /**
     * getEntityNews — relevance-scored news articles for a specific entity (PRD-0026)
     * Used by Instrument Detail → News tab
     *
     * WHY RankedNewsResponse: proxy was retargeted from S5 to S6 in Wave 7.
     * S6 returns RankedArticle[] (with source_name, display_relevance_score, etc.)
     * rather than Article[] (source, summary, tickers, sentiment).
     *
     * @param entityId - The entity UUID
     * @param params - EntityNewsParams (start_date, end_date, order_by, limit, offset)
     */
    getEntityNews(
      entityId: string,
      params: EntityNewsParams = {},
    ): Promise<RankedNewsResponse> {
      const qs = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<RankedNewsResponse>(
        `/v1/news/entity/${encodeURIComponent(entityId)}${qs ? `?${qs}` : ""}`,
        { token: t },
      );
    },

    /**
     * getRelevantNews — general relevance-ranked news feed (legacy endpoint)
     * Used by Alerts/News page → Feed tab
     */
    getRelevantNews(limit = 20): Promise<NewsResponse> {
      return apiFetch<NewsResponse>(`/v1/news/relevant?limit=${limit}`);
    },
  };
}
