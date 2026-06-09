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
 * formatGeneratedAt — ISO datetime → "12 Jun 2026 · 14:32" display string.
 * WHY not Intl.DateTimeFormat with locale: this component renders server-side
 * during hydration; a locale-sensitive format causes a server/client mismatch
 * (React hydration warning). Fixed format avoids the inconsistency.
 */
function formatGeneratedAt(iso: string): string {
  try {
    const d = new Date(iso);
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const h = String(d.getUTCHours()).padStart(2, "0");
    const m = String(d.getUTCMinutes()).padStart(2, "0");
    return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()} · ${h}:${m}`;
  } catch {
    return iso;
  }
}

// ── Sub-component: version row ────────────────────────────────────────────────

interface VersionRowProps {
  version: NarrativeVersionPublic;
}

function VersionRow({ version }: VersionRowProps) {
  // WHY details element: progressive disclosure without a second state layer.
  // Keeping each row's expand-state local avoids lifting to the parent (which
  // would require N useState slots for N versions).
  return (
    <details className="group py-1 border-b border-border/40 last:border-0">
      <summary className="flex items-center gap-2 cursor-pointer list-none">
        <span className="text-[10px] font-mono text-muted-foreground tabular-nums">
          {formatGeneratedAt(version.generated_at)}
        </span>
        <span className="text-[9px] bg-muted text-muted-foreground px-1 py-0.5 rounded-[2px] font-mono truncate max-w-[80px]">
          {version.model_id.split("/").pop()}
        </span>
        {/* First 80 chars of narrative as a one-liner preview */}
        <span className="text-[10px] text-foreground/70 truncate flex-1">
          {version.narrative_text.slice(0, 80)}…
        </span>
      </summary>
      {/* Expanded: full narrative_text, max 400px, scrollable */}
      <div className="mt-1 max-h-[400px] overflow-y-auto">
        <p className="text-[10px] text-foreground/80 leading-relaxed whitespace-pre-wrap">
          {version.narrative_text}
        </p>
      </div>
    </details>
  );
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

          {/* ── Version list ────────────────────────────────────────────────── */}
          {allVersions.length === 0 ? (
            <p className="text-[10px] text-muted-foreground italic">
              Only the current version exists.
            </p>
          ) : (
            <div className="space-y-0">
              {allVersions.map((v) => (
                <VersionRow key={v.version_id} version={v} />
              ))}
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
