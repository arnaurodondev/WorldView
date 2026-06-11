/**
 * components/dashboard/ai-signals/group-signals.ts — pure grouping logic
 *
 * WHY A SEPARATE FILE: this is the widget's only non-trivial data transform.
 * Keeping it a pure function (signals in → groups out, no React, no hooks)
 * makes it directly unit-testable without rendering anything — the same
 * pattern the backend uses for _dedup_signals in routes/signals.py.
 *
 * WHO USES IT: AiSignalsWidget.tsx (inside a useMemo so the grouping only
 * recomputes when the query data changes, not on every render).
 */

import type { EnrichedAiSignal, SignalGroup } from "./types";

/**
 * groupSignalsByEntity — collapse a flat signal list into per-entity groups.
 *
 * Contract:
 *  - input order is assumed newest-first (S9 returns created_at DESC);
 *  - one group per entity_id, in order of each entity's newest signal;
 *  - group.top = newest non-NEUTRAL signal if any, else the newest signal
 *    (direction is the headline information when we have it);
 *  - signals inside a group keep their newest-first order.
 *
 * WHY group by entity_id (not ticker): ticker can be null for entities that
 * are not listed instruments (people, commodities, sectors). entity_id is the
 * one identifier every signal carries.
 */
export function groupSignalsByEntity(signals: EnrichedAiSignal[]): SignalGroup[] {
  // Map preserves insertion order — first time we see an entity defines the
  // group's position, and input is newest-first, so groups end up ordered by
  // "entity's most recent signal" automatically.
  const groups = new Map<string, SignalGroup>();

  for (const signal of signals) {
    // Defensive: skip rows with no entity_id at all (cannot group or navigate).
    if (!signal.entity_id) continue;

    const existing = groups.get(signal.entity_id);
    if (!existing) {
      groups.set(signal.entity_id, {
        key: signal.entity_id,
        ticker: signal.ticker ?? null,
        // entity_name is the enriched field; older payloads won't have it.
        name: signal.entity_name ?? null,
        entityId: signal.entity_id,
        signals: [signal],
        top: signal,
      });
      continue;
    }

    existing.signals.push(signal);
    // Backfill ticker/name from later rows — enrichment can be partial when
    // the KG only resolved some of an entity's rows (defensive, cheap).
    if (!existing.ticker && signal.ticker) existing.ticker = signal.ticker;
    if (!existing.name && signal.entity_name) existing.name = signal.entity_name;
    // Promote a directional signal to `top` if the current top is NEUTRAL.
    // We never demote: the FIRST directional signal seen is also the NEWEST
    // directional one (input is newest-first).
    if (existing.top.label === "NEUTRAL" && signal.label !== "NEUTRAL") {
      existing.top = signal;
    }
  }

  return Array.from(groups.values());
}
