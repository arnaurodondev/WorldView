/**
 * context/NarrativeHistoryDisclosure.tsx — narrative version history accordion
 * for the Intelligence right rail (W7 Block I, T-13).
 *
 * WHY THIS EXISTS: The KG pipeline (Worker 13C) periodically regenerates entity
 * narratives. This disclosure lets analysts inspect the history of how the AI's
 * interpretation of an entity has evolved, and manually trigger a fresh generation.
 *
 * DESIGN REFERENCE: W7 §1 check 13 (Δ22); T-13 spec (≤100 LOC).
 * DATA SOURCE: useEntityNarrativeHistory(entityId) → iqk.narratives cache key
 *              useTriggerNarrativeGeneration(entityId) → POST .../narratives/generate
 *
 * WHO USES IT: ContextPanel (entity-overview mode, 5th block).
 *
 * POLLING (Δ22): After a POST 202, polls for a new version every 3s × 10 attempts.
 * On the 10th attempt (or when a new version appears), polling stops.
 */

"use client";
// WHY "use client": infinite query, mutations, and polling intervals require
// React state and browser APIs.

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useEntityNarrativeHistory, useTriggerNarrativeGeneration } from "@/lib/api/intelligence";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/skeleton";
import type { NarrativeVersionPublic } from "@/types/intelligence";
// Round-2 item 4: timeline rendering (date + headline + marker column,
// most recent at top) replaces the old flat VersionRow list.
import { NarrativeTimeline, type NarrativeTimelineEntry } from "./NarrativeTimeline";
// WHY iqk is not exported from intelligence.ts: we re-derive the same key shape
// used by useEntityNarrativeHistory (["entity-narratives", entityId]) for targeted
// invalidation during the post-202 polling cycle. TanStack Query uses deep-equality
// so the shape must match exactly.
import { qk } from "@/lib/query/keys";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Polling: check for new version every 3s after a POST 202 (Δ22). */
const POLL_INTERVAL_MS = 3_000;
/** Polling: give up after 10 polls (~30s) to avoid runaway background activity. */
const MAX_POLLS = 10;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * headlineOf — derive a one-line headline from the full narrative text
 * (Round-2 item 4). The narrative has no dedicated title field, so the first
 * sentence IS the headline (KG narratives open with a thesis sentence, e.g.
 * "Apple Inc. is a leading technology company that competes with…").
 * Capped at 110 chars with an ellipsis so a run-on opener can't wrap the
 * timeline row into a paragraph.
 */
function headlineOf(narrativeText: string): string {
  const firstSentence = narrativeText.split(/(?<=\.)\s+/, 1)[0] ?? narrativeText;
  const trimmed = firstSentence.trim();
  return trimmed.length > 110 ? `${trimmed.slice(0, 110).trimEnd()}…` : trimmed;
}

/**
 * toTimelineEntries — NarrativeVersionPublic[] → NarrativeTimelineEntry[].
 *
 * WHY sentiment is NEVER set here: the S9 payload carries no per-version
 * sentiment field (verified live 2026-06-10 — keys are version_id,
 * narrative_text, model_id, generation_reason, generated_at, word_count,
 * quality_score). The timeline renders a hollow marker for undefined
 * sentiment; fabricating "neutral" client-side would misrepresent unscored
 * data as scored. When the backend adds the field, map it through here.
 */
function toTimelineEntries(versions: NarrativeVersionPublic[]): NarrativeTimelineEntry[] {
  return versions.map((v) => ({
    id: v.version_id,
    date: v.generated_at,
    headline: headlineOf(v.narrative_text),
    fullText: v.narrative_text,
  }));
}

// ── Main component ────────────────────────────────────────────────────────────

export interface NarrativeHistoryDisclosureProps {
  readonly entityId: string;
}

export function NarrativeHistoryDisclosure({ entityId }: NarrativeHistoryDisclosureProps) {
  const qc = useQueryClient();
  const narrativesQuery = useEntityNarrativeHistory(entityId);
  const triggerMutation = useTriggerNarrativeGeneration(entityId);

  // ── Post-202 polling (Δ22) ────────────────────────────────────────────────
  const [pollCount, setPollCount] = useState(0);
  const [polling, setPolling] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!polling || pollCount >= MAX_POLLS) {
      setPolling(false);
      return;
    }
    pollTimerRef.current = setTimeout(async () => {
      await qc.invalidateQueries({ queryKey: qk.kg.narratives(entityId) });
      setPollCount((n) => n + 1);
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [polling, pollCount, entityId, qc]);

  // All versions across all loaded pages
  const allVersions: NarrativeVersionPublic[] =
    narrativesQuery.data?.pages.flatMap((p) => p.versions) ?? [];

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (narrativesQuery.isLoading) {
    return <Skeleton className="h-8 w-full" />;
  }

  return (
    // WHY type="single" collapsible: only one panel open at a time; default
    // collapsed satisfies acceptance check 13 (NarrativeHistoryDisclosure
    // collapsed by default).
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="narrative-history" className="border-border/40">
        <AccordionTrigger className="text-[10px] font-mono uppercase tracking-wider py-1.5 hover:no-underline">
          <span>Narrative History</span>
          <span className="ml-auto mr-2 text-[9px] text-muted-foreground tabular-nums">
            {allVersions.length} version{allVersions.length !== 1 ? "s" : ""}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          {/* ── Refresh button ─────────────────────────────────────────────── */}
          <div className="flex items-center justify-between mb-2">
            <span className="text-[9px] text-muted-foreground">
              {polling ? `Checking… (${pollCount}/${MAX_POLLS})` : "Trigger fresh generation"}
            </span>
            <button
              type="button"
              onClick={() => {
                triggerMutation.mutate(undefined, {
                  onSuccess: () => {
                    // Start polling for the new version (Δ22: 3s × 10)
                    setPollCount(0);
                    setPolling(true);
                  },
                });
              }}
              disabled={triggerMutation.isPending || polling}
              className="text-[9px] font-mono uppercase tracking-wider px-2 py-0.5 border border-border/60 hover:bg-muted disabled:opacity-40"
            >
              {triggerMutation.isPending ? "Queuing…" : "Refresh"}
            </button>
          </div>

          {/* ── Version timeline (Round-2 item 4) ──────────────────────────────
              Most recent at top; each entry = date + first-sentence headline,
              expandable to the full narrative. The timeline itself owns the
              zero-entries named empty state, so no branch is needed here. */}
          <NarrativeTimeline entries={toTimelineEntries(allVersions)} />
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
