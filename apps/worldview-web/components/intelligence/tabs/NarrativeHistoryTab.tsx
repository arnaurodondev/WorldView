/**
 * components/intelligence/tabs/NarrativeHistoryTab.tsx — Narrative version timeline tab
 * (PLAN-0074 Wave H T-H-04)
 *
 * WHY THIS EXISTS:
 * Narrative history lets analysts see how the AI's understanding of an entity
 * has evolved over time. Seeing a narrative shift from "growth company" to
 * "value trap" over three quarters is a high-signal data point that no static
 * summary can provide. The timeline format makes evolution immediately legible.
 *
 * WHY INFINITE SCROLL:
 * Active entities can accumulate 50+ narrative versions. Loading all at once
 * is wasteful. The "Load more" button at the bottom triggers the next page
 * only when the analyst wants it — no surprise data loads.
 *
 * WHY GENERATION REASON COLORS:
 * The reason badge tells analysts WHY the narrative changed:
 *   INITIAL = gray (first-time generation, no baseline)
 *   PERIODIC_REFRESH = blue (scheduled update, normal)
 *   MANUAL_TRIGGER = amber (analyst triggered it — high signal)
 *   QUALITY_IMPROVEMENT = green (model upgraded, improved output)
 *   OTHER = gray
 *
 * WHY EXPAND ON CLICK:
 * The narrative_text can be 400-800 words. Collapsed cards show 3 lines;
 * expanding reveals the full text inline without a modal/drawer, keeping
 * the analyst in context.
 *
 * WHO USES IT: IntelligencePanel (Narratives tab)
 */

"use client";

import { useState } from "react";
import { useEntityNarrativeHistory } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import type { NarrativeVersionPublic } from "@/types/intelligence";

// ── Props ─────────────────────────────────────────────────────────────────────

interface NarrativeHistoryTabProps {
  entityId: string;
}

// ── Generation reason styling ─────────────────────────────────────────────────

type ReasonBadgeStyle = { label: string; classes: string };

function getReasonStyle(reason: string): ReasonBadgeStyle {
  // WHY switch on reason string: the backend emits string constants, not an
  // enum we can import. Using a switch is exhaustive and maps directly to the
  // badge colors documented in the module comment.
  switch (reason.toUpperCase()) {
    case "INITIAL":
      return { label: "Initial", classes: "bg-muted text-muted-foreground" };
    case "PERIODIC_REFRESH":
      // WHY accent-ai: design token for AI/scheduled operations (PLAN-0071 rule)
      return { label: "Scheduled", classes: "bg-accent-ai/15 text-accent-ai" };
    case "MANUAL_TRIGGER":
      return { label: "Manual", classes: "bg-primary/15 text-primary" };
    case "QUALITY_IMPROVEMENT":
      return { label: "Improved", classes: "bg-positive/15 text-positive" };
    default:
      return { label: reason, classes: "bg-muted text-muted-foreground" };
  }
}

// ── NarrativeCard sub-component ───────────────────────────────────────────────

function NarrativeCard({ version }: { version: NarrativeVersionPublic }) {
  const [expanded, setExpanded] = useState(false);
  const { label: reasonLabel, classes: reasonClasses } = getReasonStyle(
    version.generation_reason,
  );

  return (
    <div className="rounded-[2px] border border-border/50 bg-card/40 p-3 mb-2">
      {/* ── Card header ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 mb-2">
        {/* Generation reason badge */}
        <span
          className={`inline-block rounded-[2px] px-1.5 py-0.5 text-[10px] font-mono font-medium uppercase tracking-wider ${reasonClasses}`}
        >
          {reasonLabel}
        </span>

        {/* Model ID chip */}
        <span className="inline-block rounded-[2px] px-1.5 py-0.5 bg-muted/60 text-muted-foreground text-[10px] font-mono border border-border/40 truncate max-w-[140px]" title={version.model_id}>
          {version.model_id.split("/").pop() ?? version.model_id}
        </span>

        {/* Word count */}
        {version.word_count != null && (
          <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
            {version.word_count}w
          </span>
        )}

        {/* Generated at timestamp — right-aligned */}
        <span className="ml-auto text-[10px] font-mono tabular-nums text-muted-foreground">
          {new Intl.DateTimeFormat("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          }).format(new Date(version.generated_at))}
        </span>
      </div>

      {/* ── Narrative text (collapsed / expanded) ────────────────────────── */}
      {/* WHY line-clamp-3 when collapsed:
          3 lines of text gives enough context to assess the narrative tone
          without consuming too much vertical space in the timeline. */}
      <p
        className={cn(
          "text-[11px] text-foreground/80 leading-relaxed font-sans whitespace-pre-wrap",
          !expanded && "line-clamp-3",
        )}
      >
        {version.narrative_text}
      </p>

      {/* Expand / collapse toggle button */}
      {version.narrative_text.length > 200 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1.5 flex items-center gap-1 text-[10px] font-mono text-muted-foreground hover:text-foreground transition-colors"
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse narrative" : "Expand full narrative"}
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" strokeWidth={1.5} />
              Collapse
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" strokeWidth={1.5} />
              Read more
            </>
          )}
        </button>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function NarrativeHistoryTab({ entityId }: NarrativeHistoryTabProps) {
  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useEntityNarrativeHistory(entityId);

  if (isLoading) {
    return (
      <div className="p-3 space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-[80px] w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        Failed to load narrative history
      </div>
    );
  }

  // Flatten paginated pages into a single array
  const allVersions: NarrativeVersionPublic[] =
    data?.pages.flatMap((page) => page.items) ?? [];

  if (allVersions.length === 0) {
    return (
      <div className="p-3 text-center text-[11px] text-muted-foreground font-mono">
        No narrative history yet
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-3">
      {/* WHY total in header: lets analysts know if there are many more versions
          beyond what's currently visible (e.g., "12 of 47 narratives loaded"). */}
      <p className="text-[10px] font-mono text-muted-foreground mb-3">
        {data?.pages[0]?.total ?? allVersions.length} narrative versions
      </p>

      {/* Timeline — most recent first */}
      {allVersions.map((version) => (
        <NarrativeCard key={version.version_id} version={version} />
      ))}

      {/* Load more button */}
      {hasNextPage && (
        <div className="flex justify-center py-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchNextPage()}
            disabled={isFetchingNextPage}
            className="text-[11px] h-7"
            aria-label="Load more narrative history"
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
