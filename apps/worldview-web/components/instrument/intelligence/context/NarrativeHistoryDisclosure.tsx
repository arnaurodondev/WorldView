/**
 * context/NarrativeHistoryDisclosure.tsx — collapsible narrative version history (W7 T-13)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — the Intelligence right rail shows the complete
 * version history of the entity's AI-generated narrative so analysts can track
 * how the KG pipeline's understanding has evolved over time. A collapsed Accordion
 * keeps the rail compact by default while making the history accessible on demand.
 *
 * WHO USES IT: ContextPanel (entity-overview mode, bottom section).
 * DATA SOURCE: GET /v1/entities/{id}/narratives → NarrativeHistoryPage (first page only).
 * DESIGN REFERENCE: W7 design doc §5.5 (NarrativeHistoryDisclosure, 32px rows).
 *
 * WHY useQuery (not useInfiniteQuery):
 * The Accordion shows at most ~10 versions before becoming unwieldy in the narrow
 * rail. Loading the first page (default 20 from S9) is sufficient. Full cursor-
 * paginated history is available via useEntityNarrativeHistory (infinite scroll)
 * in a future full-screen history view.
 *
 * WHY COLLAPSED BY DEFAULT:
 * Narrative history is a "drill-down" feature — most analysts want to see the
 * current brief at a glance, not scroll through the 20-version archive on every
 * page load. The Accordion follows the same expand-on-demand pattern as the
 * shadcn Accordion used in FinancialsFundamentals.
 */

"use client";
// WHY "use client": useQuery + useState for expanded narrative rows require browser.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { formatDateTime } from "@/lib/utils";
import type { NarrativeVersionPublic } from "@/types/intelligence";

export interface NarrativeHistoryDisclosureProps {
  readonly entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NarrativeHistoryDisclosure({ entityId }: NarrativeHistoryDisclosureProps) {
  const gateway = useApiClient();
  // WHY local expanded set (not global state): each version row can be expanded
  // independently. A Set of version_ids gives O(1) toggle without lifting state.
  const [expandedVersionIds, setExpandedVersionIds] = useState<Set<string>>(new Set());

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.kg.narratives(entityId),
    queryFn: () => gateway.getNarratives(entityId),
    staleTime: 5 * 60 * 1000, // WHY 5 min: matches S9 backend cache TTL for narrative history
    enabled: !!entityId,
  });

  const versions = data?.versions ?? [];

  // ── Toggle a version row's expanded state ─────────────────────────────────
  const toggleVersion = (id: string) => {
    setExpandedVersionIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    // WHY Accordion: shadcn Accordion handles keyboard accessibility (arrow keys,
    // Enter/Space to expand) and emits no animation on closed state by default —
    // the accordion-down keyframe (tailwind.config.ts) activates only on open.
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="narrative-history" className="border-none">
        <AccordionTrigger className="px-3 py-1 text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground hover:no-underline hover:text-foreground">
          NARRATIVE HISTORY
        </AccordionTrigger>
        <AccordionContent>
          {isLoading && (
            <div className="px-3 py-1 space-y-1">
              <Skeleton className="h-[32px] w-full" />
              <Skeleton className="h-[32px] w-full" />
            </div>
          )}

          {isError && (
            <p className="text-[11px] text-muted-foreground px-3 py-2">
              Narrative history unavailable.
            </p>
          )}

          {!isLoading && !isError && versions.length === 0 && (
            <p className="text-[11px] text-muted-foreground px-3 py-2">
              No narrative history available.
            </p>
          )}

          {!isLoading && !isError && versions.length > 0 && (
            // WHY overflow-y-auto + max-h: cap the expanded list height so it
            // doesn't push the page scrollbar. 400px ≈ 12 rows at 32px each.
            <div className="overflow-y-auto max-h-[400px]">
              {versions.map((v: NarrativeVersionPublic) => {
                const isExpanded = expandedVersionIds.has(v.version_id);
                const preview = v.narrative_text.slice(0, 80);

                return (
                  <button
                    key={v.version_id}
                    type="button"
                    onClick={() => toggleVersion(v.version_id)}
                    className="w-full text-left px-3 border-b border-border-subtle hover:bg-muted/20 transition-color-only duration-100"
                  >
                    {/* ── 32px summary row ──────────────────────────────── */}
                    <div className="h-[32px] flex items-center gap-2">
                      {/* WHY formatDateTime: analysts need the exact UTC timestamp to
                          correlate narrative generation with pipeline events. */}
                      <span className="text-[9px] font-mono tabular-nums text-muted-foreground w-[110px] shrink-0">
                        {formatDateTime(v.generated_at)}
                      </span>
                      {/* WHY last 10 chars of model_id: "Meta-Llama-3.1-8B-Instruct" is 27
                          chars — too wide for the rail. The last segment is unique enough. */}
                      <span className="text-[9px] font-mono text-muted-foreground/70 truncate flex-1">
                        {v.model_id.split("/").pop() ?? v.model_id}
                      </span>
                      <span className="text-[10px] text-foreground/60 truncate max-w-[80px]">
                        {preview}…
                      </span>
                    </div>

                    {/* ── Expanded full narrative ───────────────────────── */}
                    {isExpanded && (
                      <p className="text-[11px] text-foreground/80 leading-relaxed py-2 whitespace-pre-wrap">
                        {v.narrative_text}
                      </p>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
