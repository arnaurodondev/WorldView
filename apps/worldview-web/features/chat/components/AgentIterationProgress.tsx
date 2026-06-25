/**
 * features/chat/components/AgentIterationProgress.tsx
 *
 * WHY THIS EXISTS (PLAN-0099 W4 UX fix):
 * The rag-chat tool loop now emits an `agent_iteration` SSE event at every
 * transition (planning → reasoning over tool results → synthesizing). Without
 * a visible signal in the UI, a 25-second research query feels broken: the
 * user sees tool spinners for 8 seconds, then DEAD SILENCE for ~15 seconds
 * while the LLM reasons over results, then synthesis begins. This component
 * renders an always-visible progress strip that NEVER goes blank between
 * tool batches — eliminating the perceived hang.
 *
 * RELATIONSHIP TO ToolCallIndicator:
 * `ToolCallIndicator` shows per-tool spinners (search_documents, query_kg,
 * etc.). It is correct but goes BLANK during the silent reasoning gaps —
 * because the tools have completed and the LLM is now just thinking. This
 * component sits ALONGSIDE (above) ToolCallIndicator and stays visible
 * through the gaps. The two components are complementary, not redundant:
 *   ToolCallIndicator → "what tools ran (and their status)"
 *   AgentIterationProgress → "what the AGENT is doing right now"
 *
 * VISUAL DENSITY:
 * Single 32px-ish row, monospace 11px to match the rest of the chat chrome
 * (PRD-0028 §6.9 terminal density). No box / no border — just an icon, label,
 * and a right-aligned elapsed-time chip. Anything heavier would crowd the
 * streaming bubble.
 *
 * COLOR PALETTE (Midnight Pro tokens only — Bloomberg terminal mandate):
 *   - primary    → active "in progress" accent (yellow on the dark theme)
 *   - muted-foreground → secondary/elapsed text
 *   - bg-muted/40 → faint chip backdrop for the elapsed seconds
 * NO off-palette colors (blue-500, green-400, etc.) — see DESIGN_SYSTEM.md.
 *
 * ANIMATION (Round 4 sweep — DESIGN_SYSTEM.md §6.2):
 * `animate-skeleton-pulse` on the icon is the ONLY motion. Tailwind's raw
 * `animate-pulse` is BANNED platform-wide (fast consumer-app pulse that
 * bypasses our reduced-motion semantics); §6.2 sanctions exactly one opt-in
 * tier — `animate-skeleton-pulse` (slow 2s opacity fade, tailwind.config.ts)
 * for long loads (>2s expected, e.g. AI generation) where "still working"
 * feedback matters. This strip exists PRECISELY for that case: it covers the
 * multi-second silent reasoning gaps of agentic answers, and it is chrome
 * (an icon next to a status label), not a data surface — no numbers ever
 * pulse. We pair it with motion-reduce:animate-none so users with
 * prefers-reduced-motion get a static icon (the text label alone still
 * communicates the live stage). We still deliberately do NOT use
 * animate-spin (Bloomberg mandate forbids spinners on prose surfaces) and
 * NOT animate-bounce (too playful for a finance tool).
 */

"use client";
// WHY "use client": this component receives runtime state from useChatStream
// (a client-only hook). It renders no server data; the directive guards it
// against accidental import into a server component subtree.

import { Brain, Cpu, PencilLine } from "lucide-react";
// WHY these three icons:
// - Brain   → "planning_tools" reads as cognition / strategy formation
// - Cpu     → "reasoning_over_results" reads as computation over data; we
//             considered Activity but Cpu is more "the model is working"
// - PencilLine → "synthesizing" reads as composition / writing the final answer
// All three are available in lucide-react (already a dep via shadcn/ui) so no
// new dependency is required.

import type { AgentIterationEvent } from "@/features/chat/lib/types";

interface AgentIterationProgressProps {
  /**
   * The latest `agent_iteration` event from useChatStream. Null in the initial
   * state before any event has arrived — the component renders nothing in that
   * case (avoids a blank reserved row above empty bubbles).
   */
  event: AgentIterationEvent | null;
}

/**
 * Internal helper — picks the icon, primary label, and accessibility label for
 * each stage. Extracted to keep the JSX small and to make the stage→view-model
 * mapping easy to scan in code review.
 *
 * WHY a small map (not a switch in JSX): switches in JSX produce noisy diffs
 * when copy changes. A pure data table makes copy edits a one-line change.
 */
function viewModelFor(event: AgentIterationEvent): {
  Icon: typeof Brain;
  label: string;
  ariaLabel: string;
} {
  if (event.stage === "planning_tools") {
    return {
      Icon: Brain,
      // WHY "Planning approach…": the user just submitted a question; the
      // agent is deciding which tools to invoke. "Approach" hints at strategy
      // without claiming "I'm thinking" (which can read as anthropomorphic).
      label: "Planning approach…",
      ariaLabel: "Agent is planning which tools to call",
    };
  }
  if (event.stage === "reasoning_over_results") {
    // Iteration is 0-indexed on the wire; humans read 1-indexed steps.
    // We pin to "Step {i+1} of {max}" because "Iteration 3" is jargon.
    const step = event.iteration + 1;
    const total = event.tools_completed_total;
    // Singular vs plural — small detail, big polish. "1 result" vs "2 results".
    const resultsWord = total === 1 ? "result" : "results";
    return {
      Icon: Cpu,
      label: `Step ${step} of ${event.max_iterations} · Reasoning over ${total} ${resultsWord}…`,
      ariaLabel: `Reasoning over ${total} ${resultsWord} on step ${step} of ${event.max_iterations}`,
    };
  }
  // synthesizing
  return {
    Icon: PencilLine,
    // WHY "Writing answer…": the synthesis call is where the streamed
    // token output begins. "Writing" matches what the user is about to
    // SEE happen (text appears below) — clearer than "Synthesizing".
    label: "Writing answer…",
    ariaLabel: "Agent is writing the final answer",
  };
}

/**
 * AgentIterationProgress — always-visible progress strip above the streaming
 * bubble. Renders nothing until the first event arrives, then stays visible
 * through every silent gap until the stream completes (parent component
 * controls visibility by passing null when the stream ends).
 *
 * VISIBILITY CONTRACT WITH PARENT:
 * - parent passes `event=null` → component renders nothing
 * - parent passes `event=<AgentIterationEvent>` → component renders the strip
 * - parent must clear the event (set to null) when the stream completes,
 *   otherwise the strip would persist alongside the final answer.
 */
export function AgentIterationProgress({ event }: AgentIterationProgressProps) {
  // Guard: nothing to show before the first event. We deliberately return
  // null (not an empty div) so we don't reserve vertical space — the strip
  // appearing is itself a useful signal that "the agent is now working".
  if (!event) return null;

  const { Icon, label, ariaLabel } = viewModelFor(event);

  // Round milliseconds to whole seconds for the elapsed chip.
  // WHY Math.round (not Math.floor): a 1500ms event reads more naturally as
  // "2s" than "1s" — closer to the user's wall-clock perception. The test
  // pins this behaviour so a future refactor doesn't silently switch to floor.
  const elapsedSeconds = Math.round(event.elapsed_ms / 1000);

  return (
    <div
      // WHY role="status" + aria-live="polite":
      //   - role="status" tags this region as a status update for assistive tech
      //   - aria-live="polite" makes screen readers announce stage changes
      //     WITHOUT interrupting the user's current narration. We never want
      //     to be louder than the answer text itself.
      role="status"
      aria-live="polite"
      aria-label={ariaLabel}
      // Layout: single row, vertical centering, gap between icon/text/chip.
      // px-2 py-1 keeps the strip tight (32px-ish total) so it doesn't compete
      // with the streaming bubble for visual weight.
      // text-[11px] font-mono — matches ToolCallIndicator / streaming density.
      // text-primary on the icon's parent ensures the icon picks up the
      // active accent color through `currentColor` inheritance.
      className="flex items-center gap-2 px-2 py-1 text-[11px] font-mono text-muted-foreground"
    >
      {/*
       * Icon:
       * - h-3.5 w-3.5 to balance the 11px text without towering over it.
       * - text-primary so the icon picks up the Midnight Pro accent — the
       *   primary signal that "this is the live status, not a passive label".
       * - animate-skeleton-pulse (NOT raw animate-pulse, which §6.2 bans;
       *   NOT spin/bounce) — the sanctioned slow 2s "still working" fade for
       *   AI-generation waits; see the file-level ANIMATION comment for the
       *   full justification.
       * - motion-reduce:animate-none — prefers-reduced-motion users get a
       *   static icon; the live text label carries the signal on its own.
       * - aria-hidden because the surrounding role="status" already announces
       *   the state textually; the icon is decorative.
       */}
      <Icon
        className="h-3.5 w-3.5 shrink-0 text-primary animate-skeleton-pulse motion-reduce:animate-none"
        aria-hidden="true"
        strokeWidth={1.5}
      />

      {/*
       * Primary label takes available width. flex-1 + min-w-0 lets long copy
       * truncate gracefully on narrow viewports (mobile inspector panel).
       */}
      <span className="flex-1 min-w-0 truncate">{label}</span>

      {/*
       * Elapsed chip on the right:
       * - bg-muted/40 → very faint backdrop (off-palette greys forbidden)
       * - rounded-[2px] → matches the rest of the terminal chrome (PRD-0028)
       * - tabular-nums → digit widths stay constant so the chip doesn't
       *   re-flow as 9→10→11s ticks past
       * - tooltip via title= so power-users can see the precise ms.
       */}
      <span
        className="shrink-0 rounded-[2px] bg-muted/40 px-1.5 py-0.5 tabular-nums text-muted-foreground"
        title={`${event.elapsed_ms} ms`}
      >
        {elapsedSeconds}s
      </span>
    </div>
  );
}
