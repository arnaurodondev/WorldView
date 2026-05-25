/**
 * lib/api/news.ts — News feeds (top-ranked, per-entity, legacy relevant).
 *
 * Backed by S6 NLP-pipeline (PRD-0026 ranking) for `/v1/news/top` and
 * `/v1/news/entity/*`; S5 content-store still serves `/v1/news/relevant`.
 */

import type {
  ArticleImpactHistoryResponse,
  ClusterArticlesResponse,
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
     * WHY token sent (BP-545): S9 rate-limits unauthenticated requests far more
     * aggressively than authenticated ones. Sending the token places the request
     * in the user's own rate-limit bucket, preventing 429s on the dashboard when
     * multiple tabs or rapid refetches occur.
     * WHY RankedNewsResponse: S6 NLP Pipeline (not S5 Content Store) now serves
     * this endpoint, returning the richer RankedArticle shape with multi-window
     * price impact scores and LLM relevance scores. Proxy retargeted in Wave 7.
     * WHY tickers param: pass comma-separated portfolio tickers so S9 can server-side
     * filter to portfolio-relevant articles before returning the ranked feed.
     *
     * @param params - TopNewsParams (hours, limit, offset, min_display_score, routing_tier, tickers)
     */
    getTopNews(params: TopNewsParams = {}): Promise<RankedNewsResponse> {
      const qs = new URLSearchParams(
        // WHY filter null/undefined: URLSearchParams(undefined) → "undefined" string.
        // This filter ensures only explicitly set params appear in the query string.
        Object.entries(params)
          .filter(([, v]) => v != null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return apiFetch<RankedNewsResponse>(`/v1/news/top${qs ? `?${qs}` : ""}`, { token: t });
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

    /**
     * getClusterArticles — fetch all sibling articles in a near-duplicate cluster (P2-F)
     * Used by: ClusterArticlesModal (opened when the user clicks the "+N sim" chip)
     *
     * WHY no auth: cluster data is public (same posture as /v1/news/top).
     * WHY separate method (not inline in the component): keeps all S9 calls in
     * lib/api/news.ts for discoverability and mock-ability in tests.
     *
     * @param clusterId - UUID string of the duplicate cluster (from RankedArticle.cluster_id)
     */
    getClusterArticles(clusterId: string): Promise<ClusterArticlesResponse> {
      return apiFetch<ClusterArticlesResponse>(`/v1/news/cluster/${encodeURIComponent(clusterId)}`);
    },

    /**
     * getArticleImpactHistory — 4-window price-impact scores for a single article.
     *
     * WHY this exists: the ArticleImpactDrawer (PLAN-0091 C-2) shows analysts
     * whether a news article moved the stock price in the 0/1/2/5 trading days
     * after publication — this is the "did the market react?" signal that justifies
     * paying attention to the article. Without it, analysts can't distinguish a
     * high-relevance article that moved the market from one that didn't.
     *
     * WHY requires auth: S9 enforces tenant scoping via X-Internal-JWT so one
     * user can't see another tenant's price-impact computations.
     *
     * Returns null on 404 (article not yet scored by the labelling worker).
     *
     * @param articleId - The article UUID (from RankedArticle.article_id)
     */
    async getArticleImpactHistory(articleId: string): Promise<ArticleImpactHistoryResponse | null> {
      // WHY GatewayError import: impact-history returns 404 when the
      // PriceImpactLabellingWorker hasn't processed this article yet.
      // The drawer should show an empty state, not throw to the error boundary.
      try {
        return await apiFetch<ArticleImpactHistoryResponse>(
          `/v1/articles/${encodeURIComponent(articleId)}/impact-history`,
          { token: t },
        );
      } catch (err: unknown) {
        // Inline the 404 check rather than importing GatewayError to keep
        // this file's import surface minimal (news.ts has no other error handling).
        if (
          typeof err === "object" &&
          err !== null &&
          "status" in err &&
          (err as { status: number }).status === 404
        ) {
          return null;
        }
        throw err;
      }
    },
  };
}
