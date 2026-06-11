/**
 * components/dashboard/ai-signals/types.ts — enriched AI-signal types
 *
 * WHY THIS EXISTS: the 2026-06-10 AI-Signals overhaul added fields to the S9
 * GET /v1/signals/ai payload (entity_name, signal_type, polarity, article_url,
 * market_impact_score, …) but the shared `AiSignal` interface in types/api.ts
 * still describes the legacy shape. We extend it HERE (instead of editing
 * types/api.ts) because:
 *   1. types/api.ts is a shared file touched by several concurrent
 *      workstreams — an additive local extension avoids merge conflicts;
 *   2. every new field is OPTIONAL, so this widget keeps working against an
 *      older S9 that only returns the legacy fields (forward compatibility,
 *      same principle as Avro schema evolution on the backend).
 *
 * WHO USES IT: AiSignalsWidget.tsx, group-signals.ts, SignalGroupRow.tsx
 * BACKEND CONTRACT: services/api-gateway routes/signals.py (ai_signals docstring)
 */

import type { AiSignal } from "@/types/api";

/**
 * EnrichedAiSignal — one deduplicated signal row from S9.
 *
 * FIELD SEMANTICS (these matter — the old widget showed numbers without
 * meaning, which is exactly what we are fixing):
 *  - `score`              = LLM *extraction confidence* (0–1): how certain the
 *                           model is that the event was actually stated in the
 *                           article. It is NOT a prediction of price movement.
 *  - `market_impact_score`= observed abnormal day-0 price move (0–1) from the
 *                           impact-labelling pipeline; 0.0 means "not labelled
 *                           yet" (the pipeline needs 25h+ of OHLCV after
 *                           publication), which is the common case today.
 *  - `label`              = direction: claim polarity from the extraction LLM
 *                           when decisive, else a signal-type heuristic.
 *  - `signal_type_label`  = human-readable event category ("Earnings", "M&A",
 *                           "Product launch", …) — humanized server-side so
 *                           the enum→copy table lives in ONE place.
 */
export interface EnrichedAiSignal extends AiSignal {
  /** Canonical entity name from the knowledge graph ("Lululemon Athletica"). */
  entity_name?: string | null;
  /** Raw S6 signal_type enum value (e.g. "EARNINGS_RELEASE"). */
  signal_type?: string | null;
  /** Human-readable signal type for the chip (e.g. "Earnings"). */
  signal_type_label?: string | null;
  /** Raw extraction polarity: "positive" | "negative" | "neutral". */
  polarity?: string | null;
  /** Observed day-0 abnormal price move 0–1; 0 = not labelled yet. */
  market_impact_score?: number | null;
  /** Link to the triggering article (opens the source, not our app). */
  article_url?: string | null;
  /** Publisher name ("Yahoo Finance"). */
  source_name?: string | null;
  /** Article publication time (ISO) — distinct from signal detection time. */
  published_at?: string | null;
}

/**
 * SignalGroup — all signals for ONE entity, newest first.
 *
 * WHY GROUPING EXISTS: the screenshot that triggered this overhaul showed
 * "BSX ×3, BAC ×3, DOW ×2 …" as undifferentiated repeated rows. Grouping by
 * entity turns repetition into INFORMATION: "BAC · 3 signals" says news flow
 * is clustering on that name — and the group expands to show each event.
 */
export interface SignalGroup {
  /** Stable grouping key — entity_id (ticker can be null, entity_id never). */
  key: string;
  /** Exchange ticker when the entity is a listed instrument; null otherwise. */
  ticker: string | null;
  /** Human-readable entity name — the fallback display when ticker is null. */
  name: string | null;
  /** Entity id used for /instruments/[id] navigation fallback. */
  entityId: string;
  /** All signals for this entity, newest first. */
  signals: EnrichedAiSignal[];
  /**
   * Representative signal shown on the collapsed row: the newest DIRECTIONAL
   * (non-NEUTRAL) signal when one exists, else simply the newest. Direction
   * is the most valuable bit on a dashboard — surface it when we have it.
   */
  top: EnrichedAiSignal;
}
