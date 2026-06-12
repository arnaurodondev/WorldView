/**
 * components/dashboard/ai-signals/types.ts — NEWS MOMENTUM feed types
 *
 * WHY THIS EXISTS: the 2026-06-12 Wave-4 pivot changed the S9 GET /v1/signals/ai
 * payload from extraction-confidence "signals" to a NEWS MOMENTUM feed (recent,
 * relevant, clickable articles). The shared ``AiSignalsResponse`` interface in
 * types/api.ts still describes the LEGACY signal shape. We model the NEW item
 * shape HERE (instead of editing types/api.ts) because:
 *   1. types/api.ts is a shared file touched by several concurrent
 *      workstreams — a local type avoids merge conflicts;
 *   2. every field on the wire item is read defensively, so this widget keeps
 *      working against an older S9 that still returns the legacy fields
 *      (forward compatibility, same principle as Avro schema evolution).
 *
 * WHO USES IT: AiSignalsWidget.tsx, NewsMomentumRow.tsx, news-meta.ts
 * BACKEND CONTRACT: services/api-gateway routes/signals.py (ai_signals docstring)
 */

/**
 * Sentiment direction rendered as a colored dot. The server normalises S6's
 * noisier enum ("mixed" → "neutral", null → "neutral") so the UI only ever
 * sees these three values — but we keep the field optional for forward-compat.
 */
export type NewsSentiment = "positive" | "negative" | "neutral";

/**
 * NewsMomentumItem — one row in the NEWS MOMENTUM feed.
 *
 * FIELD SEMANTICS (these matter — the OLD widget showed a meaningless 95%
 * extraction confidence; every field here is something the user can read or
 * act on):
 *  - `title`     = the actual news headline — the event itself.
 *  - `url`       = link to the source article (opens the publisher, not us).
 *  - `source`    = short publisher label derived from the URL host ("yahoo").
 *  - `relevance` = HONEST display_relevance_score (0–1): a real composite of
 *                  market impact + LLM relevance + routing (PRD-0026 §6.5).
 *                  This REPLACES the fake 0.90/0.95 extraction confidence.
 *  - `sentiment` = direction of the news for the dot (positive/negative/neutral).
 *  - `published_at` = when the article was published → drives recency.
 *  - `market_impact_score` = observed day-0 abnormal price move (0–1) when the
 *                  article has been impact-labelled; null otherwise (common —
 *                  labelling needs 25h+ of post-publication OHLCV).
 *
 * Every field is OPTIONAL so a stale S9 (legacy signal payload) degrades to an
 * empty/partial row rather than throwing.
 */
export interface NewsMomentumItem {
  /** Stable id for the React key + dedup (S6 article_id). */
  article_id?: string | null;
  /** The news headline. */
  title?: string | null;
  /** Link to the source article. */
  url?: string | null;
  /** Short publisher label ("yahoo", "fxstreet") derived server-side. */
  source?: string | null;
  /** ISO publication time — drives the relative-time column. */
  published_at?: string | null;
  /** News direction for the dot. */
  sentiment?: NewsSentiment | string | null;
  /** Honest composite relevance 0–1 (display_relevance_score). */
  relevance?: number | null;
  /** Effective routing tier ("light" | "medium" | "deep"). */
  routing_tier?: string | null;
  /** Observed day-0 abnormal price move 0–1; null = not labelled yet. */
  market_impact_score?: number | null;
}

/**
 * NewsMomentumResponse — the S9 /v1/signals/ai body after the Wave-4 pivot.
 *
 * Top-level key is still ``signals`` (preserves the widget prop contract and
 * the dashboard slot); ``window_hours`` echoes the resolved look-back window so
 * the selector can confirm which window the server actually served.
 */
export interface NewsMomentumResponse {
  signals: NewsMomentumItem[];
  /** Resolved look-back window (24 | 72 | 168). Optional for forward-compat. */
  window_hours?: number;
}
