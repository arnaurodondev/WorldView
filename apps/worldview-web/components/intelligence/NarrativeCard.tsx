/**
 * components/intelligence/NarrativeCard.tsx — Current narrative display + regenerate
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY THIS EXISTS:
 * The entity sidebar's most important element is the current AI narrative —
 * a concise summary of the entity's recent developments, risk factors, and
 * market positioning. This card displays it with:
 *   - Truncation at 400 chars with "Read more" expand
 *   - Model ID chip (analysts want to know which model generated it)
 *   - Generation reason badge
 *   - "Regenerate" button to trigger a fresh generation on demand
 *
 * WHY 400 CHAR TRUNCATION:
 * The sidebar is ~300px wide. A full narrative can be 800+ words. 400 chars
 * (~60-70 words) fits ~4 lines in the sidebar at 11px, giving analysts the
 * gist without requiring them to scroll past a wall of text to see other metrics.
 *
 * WHY TOAST (not inline error):
 * The regenerate button triggers an async job. The response is either:
 *   202 Accepted → "Queued" toast (positive)
 *   429 Too Many Requests → "Rate limited" toast (warning)
 *   Other errors → re-thrown by useMutation, shown as "error" toast
 * Using sonner toasts keeps the card UI clean — no error message that changes
 * the card's layout or requires dismiss state management.
 *
 * WHO USES IT: EntitySidebar
 * DATA SOURCE: current_narrative from useEntityIntelligence
 */

"use client";
// WHY "use client": uses useMutation (React state, hooks) + toast from sonner.

import { useState } from "react";
import { toast } from "sonner";
import { useTriggerNarrativeGeneration } from "@/lib/api/intelligence";
import { Button } from "@/components/ui/button";
import { GatewayError } from "@/lib/gateway";
import { RefreshCw } from "lucide-react";
import type { NarrativeVersionPublic } from "@/types/intelligence";

// ── Props ─────────────────────────────────────────────────────────────────────

interface NarrativeCardProps {
  entityId: string;
  narrative: NarrativeVersionPublic | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NarrativeCard({ entityId, narrative }: NarrativeCardProps) {
  // WHY local expanded state (not URL):
  // The expanded/collapsed state of the narrative card is transient UI state.
  // It should not appear in browser history or be bookmarkable. useState is correct.
  const [expanded, setExpanded] = useState(false);
  const { mutate: triggerRegenerate, isPending } = useTriggerNarrativeGeneration(entityId);

  function handleRegenerate() {
    triggerRegenerate(undefined, {
      onSuccess: () => {
        // WHY 202 Accepted toast: the job is queued, not complete.
        // Showing "success" would be misleading — the narrative isn't ready yet.
        // "Queued" accurately describes the async state.
        toast.info("Narrative generation queued");
      },
      onError: (error) => {
        if (error instanceof GatewayError && error.status === 429) {
          // WHY rate limit message: the API throttles manual regeneration to
          // prevent analysts from spamming expensive LLM calls. The 1-hour
          // message is the backend's documented cooldown period.
          toast.error("Rate limited — try again in 1 hour");
        } else {
          toast.error("Failed to queue narrative generation");
        }
      },
    });
  }

  if (!narrative) {
    return (
      <div className="space-y-2">
        <p className="text-[11px] text-muted-foreground font-mono italic">
          No narrative generated yet
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRegenerate}
          disabled={isPending}
          className="text-[11px] h-7 w-full"
          aria-label="Generate first narrative"
        >
          {isPending ? (
            <>
              <RefreshCw className="h-3 w-3 mr-1.5 animate-spin" strokeWidth={1.5} />
              Queuing…
            </>
          ) : (
            "Generate Narrative"
          )}
        </Button>
      </div>
    );
  }

  const truncated = narrative.narrative_text.length > 400
    ? narrative.narrative_text.slice(0, 400) + "…"
    : narrative.narrative_text;
  const needsTruncation = narrative.narrative_text.length > 400;

  return (
    <div className="space-y-2">
      {/* ── Narrative metadata chips ──────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-1.5">
        {/* Generation reason badge */}
        <span className="inline-block rounded-[2px] px-1.5 py-0.5 bg-primary/10 text-primary text-[10px] font-mono font-medium uppercase tracking-wider">
          {narrative.generation_reason.replace(/_/g, " ")}
        </span>
        {/* Model ID chip */}
        <span
          className="inline-block rounded-[2px] px-1.5 py-0.5 bg-muted/60 text-muted-foreground text-[10px] font-mono border border-border/40 truncate max-w-[120px]"
          title={narrative.model_id}
        >
          {narrative.model_id.split("/").pop() ?? narrative.model_id}
        </span>
      </div>

      {/* ── Narrative text ────────────────────────────────────────────────── */}
      <p className="text-[11px] text-foreground/80 leading-relaxed font-sans">
        {expanded ? narrative.narrative_text : truncated}
      </p>

      {/* Read more / collapse toggle */}
      {needsTruncation && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-[10px] font-mono text-primary hover:text-primary/80 transition-colors"
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Read more"}
        </button>
      )}

      {/* ── Regenerate button ─────────────────────────────────────────────── */}
      <Button
        variant="outline"
        size="sm"
        onClick={handleRegenerate}
        disabled={isPending}
        className="text-[11px] h-7 w-full mt-1"
        aria-label="Regenerate entity narrative"
      >
        {isPending ? (
          <>
            <RefreshCw className="h-3 w-3 mr-1.5 animate-spin" strokeWidth={1.5} />
            Queuing…
          </>
        ) : (
          <>
            <RefreshCw className="h-3 w-3 mr-1.5" strokeWidth={1.5} />
            Regenerate
          </>
        )}
      </Button>
    </div>
  );
}
