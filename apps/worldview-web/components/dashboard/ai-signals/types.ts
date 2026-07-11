/**
 * components/dashboard/ai-signals/types.ts — NEWS MOMENTUM feed types
 *
 * WHY THIS EXISTS: the NEWS MOMENTUM feed (S9 GET /v1/signals/ai) answers
 * "which ENTITY is gaining news attention right now, and is it accelerating?".
 * Each row is a tradeable ENTITY (ticker) with a momentum signal — NOT a bare
 * article. (An earlier iteration of this widget showed a flat list of recent
 * articles, which duplicated the Portfolio News widget and carried no surge
 * information; PLAN-0099 W4 made it true per-entity momentum.)
 *
 * We model the item shape HERE (instead of editing the shared types/api.ts)
 * because:
 *   1. types/api.ts is a shared file touched by several concurrent workstreams —
 *      a local type avoids merge conflicts;
 *   2. every field on the wire item is read defensively, so the widget keeps
 *      working against an older S9 (forward compatibility).
 *
 * WHO USES IT: AiSignalsWidget.tsx, NewsMomentumRow.tsx, news-meta.ts
 * BACKEND CONTRACT: services/api-gateway routes/signals.py (ai_signals docstring)
 *   → proxies S6 GET /api/v1/news/trending-entities
 */

/**
 * Sentiment direction rendered as a colored dot on the headline. The server
 * normalises S6's noisier enum ("mixed" → "neutral", null → "neutral") so the
 * UI only ever sees these three values — kept optional for forward-compat.
 */
export type NewsSentiment = "positive" | "negative" | "neutral";

/**
 * MomentumTopArticle — the entity's single most relevant recent headline.
 *
 *  - `title`     = the actual headline (the event itself), links OUT to the publisher.
 *  - `url`       = link to the source article.
 *  - `source`    = short publisher label derived from the URL host ("yahoo").
 *  - `relevance` = HONEST display_relevance_score (0–1): a real composite of
 *                  market impact + LLM relevance + routing (PRD-0026 §6.5).
 *  - `sentiment` = direction of the news for the dot (positive/negative/neutral).
 *  - `published_at` = when the article was published → drives recency.
 *
 * All fields optional → a missing/partial top_article degrades gracefully.
 */
export interface MomentumTopArticle {
  id?: string | null;
  title?: string | null;
  url?: string | null;
  source?: string | null;
  published_at?: string | null;
  sentiment?: NewsSentiment | string | null;
  relevance?: number | null;
}

/**
 * NewsMomentumItem — one row in the NEWS MOMENTUM feed (a tradeable entity).
 *
 * FIELD SEMANTICS (these are the whole point — momentum, not raw recency):
 *  - `ticker`      = the tradeable symbol (mono) → row click navigates here.
 *  - `name`        = the entity's canonical name (resolved, never a UUID stub).
 *  - `count`       = distinct articles mentioning the entity in the current window.
 *  - `prior_count` = distinct articles in the prior equal window (the baseline).
 *  - `delta`       = count − prior_count (absolute velocity, e.g. +8).
 *  - `delta_pct`   = 100 × delta / max(prior_count, 1) (relative surge, e.g. ↑200%).
 *  - `top_article` = the entity's most relevant recent headline (clickable).
 *
 * Every field is OPTIONAL so a stale/partial S9 payload degrades to a partial
 * row rather than throwing.
 */
export interface NewsMomentumItem {
  /** Canonical entity UUID — stable React key + dedup. */
  entity_id?: string | null;
  /** Tradeable symbol (the navigation target). */
  ticker?: string | null;
  /** Resolved canonical name. */
  name?: string | null;
  /** Distinct articles in the current window. */
  count?: number | null;
  /** Distinct articles in the prior equal window (baseline). */
  prior_count?: number | null;
  /** Absolute velocity: count − prior_count. */
  delta?: number | null;
  /** Relative surge: 100 × delta / prior_count (0 when is_new — no baseline). */
  delta_pct?: number | null;
  /**
   * True when prior_count === 0 (no baseline window). The row shows a "NEW" badge
   * instead of delta_pct, which is meaningless without a prior window. Prevents the
   * old fabricated "↑N00%" surges when the prior window is empty (e.g. ingestion gap).
   */
  is_new?: boolean | null;
  /** The entity's most relevant recent headline. */
  top_article?: MomentumTopArticle | null;
}

/**
 * NewsMomentumResponse — the S9 /v1/signals/ai body.
 *
 * Top-level key is ``signals`` (preserves the widget prop contract + dashboard
 * slot); ``window_hours`` echoes the resolved look-back window.
 */
export interface NewsMomentumResponse {
  signals: NewsMomentumItem[];
  /** Resolved look-back window (24 | 72 | 168). Optional for forward-compat. */
  window_hours?: number;
}
