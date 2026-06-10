/**
 * features/chat/components/ToolCallIndicator.tsx — Per-tool progress indicator
 * shown during the tool-use phase of a chat response (PLAN-0067 W11-5).
 *
 * WHY THIS EXISTS:
 * The tool-use path adds a non-streaming LLM turn of ~600ms where the backend
 * decides which tools to call and executes them (search, temporal query, etc.).
 * During this phase the SSE emitter sends `tool_call` and `tool_result` events
 * but NO token chunks yet, so the streaming bubble shows nothing and users may
 * think the chat is hung. This component renders per-tool spinners so the user
 * sees exactly what's happening before the answer text starts flowing.
 *
 * DATA FLOW:
 *   S8 SSE → useChatStream (tool_call/tool_result events) → activeTools state
 *   → chat page → StreamingBubble → ToolCallIndicator (this file)
 *
 * DESIGN CONSTRAINTS:
 * - 11px font-mono to match terminal density (PRD-0028 §6.9)
 * - lucide-react icons only (bundled with shadcn/ui, no extra deps)
 * - No animate-bounce (Bloomberg terminal mandate — spinner only, no bounce)
 * - "use client" required: this uses JSX conditionals that depend on runtime
 *   state passed from a client component (StreamingBubble)
 */

"use client";
// WHY "use client": ToolCallIndicator renders inside StreamingBubble which is
// already a client component. The directive is added defensively so this file
// can never be accidentally imported by a Server Component boundary.

import { Check, Loader2, X } from "lucide-react";

/**
 * ToolCallState — mirrors the shape of the SSE `tool_call` event data.
 *
 * WHY exported from here (not from useChatStream):
 * This type is the "view model" for tool progress. Components import it from
 * the component layer (ToolCallIndicator); the hook imports it from here too.
 * One canonical definition, co-located with the rendering logic that consumes it.
 */
export interface ToolCallState {
  /** Internal tool name from the SSE event, e.g. "search_documents". */
  name: string;
  /** User-friendly label from the SSE event, e.g. "Searching documents..." */
  label: string;
  /** Running = currently executing; ok/empty/error = completed. */
  status: "running" | "ok" | "empty" | "error";
}

interface ToolCallIndicatorProps {
  tools: ToolCallState[];
}

/**
 * ToolCallIndicator — renders per-tool progress indicators during chat streaming.
 *
 * Rendering rules:
 * - running tools: animated Loader2 spinner + label (full label with "...")
 * - ok tools: green Check icon + strikethrough label (trailing "..." stripped)
 * - error/empty tools: muted X icon + strikethrough label (trailing "..." stripped)
 * - no tools: returns null (avoids blank whitespace above the streaming answer)
 *
 * WHY running tools appear BEFORE done tools regardless of insertion order:
 * Provides a stable visual layout — done tools don't jump above running ones
 * as tools complete sequentially during a multi-tool response.
 */
export function ToolCallIndicator({ tools }: ToolCallIndicatorProps) {
  // Guard: don't add whitespace when there are no active tools.
  // WHY null (not empty div): an empty div still contributes margin/padding
  // to the flex column in StreamingBubble, which creates a visible gap when
  // no tools are active (e.g. during a plain non-tool-use response).
  if (tools.length === 0) return null;

  // Split running from done to enforce stable ordering.
  // WHY Array.filter (not sort): filter preserves original insertion order
  // within each group, which matches the order tools were called by S8.
  const running = tools.filter((t) => t.status === "running");
  const done = tools.filter((t) => t.status !== "running");

  return (
    <div
      className="flex flex-col gap-1 py-1 text-xs font-mono text-muted-foreground"
      // WHY aria-label: screen readers should announce this region as tool activity,
      // not interpret the spinner text/labels as regular chat content.
      aria-label="Tool activity"
    >
      {/* Running tools: animated spinner + full label (including "...") */}
      {running.map((t) => (
        <div key={t.name} className="flex items-center gap-2">
          {/*
           * FR-5.2 (HIGH-015): animate-spin removed per Bloomberg terminal mandate.
           * Static Loader2 icon communicates "in progress" without violating the
           * no-animation rule on interactive surfaces. The icon shape alone (circular
           * partial arc) is a universally understood loading indicator.
           */}
          <Loader2 className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span>{t.label}</span>
          {/* Round 1 Foundation: surface the RAW tool name next to the friendly
              label. WHY: the label ("Searching documents...") is ambiguous when
              several search-flavoured tools exist; the mono name
              ("search_documents") is the precise identifier an analyst can
              quote in a bug report. Muted + smaller so it reads as metadata. */}
          <span className="text-[9px] text-muted-foreground/60">{t.name}</span>
        </div>
      ))}

      {/* Completed tools: static icon + strikethrough/faded label */}
      {done.map((t) => (
        <div key={t.name} className="flex items-center gap-2">
          {/*
           * WHY text-positive Check for ok, muted X for error/empty:
           * - ok = data was retrieved successfully → positive (Terminal Dark green
           *        token) Check signals "done, trust it"
           * - error/empty = tool ran but found nothing or errored → X signals "done, no data"
           *   (muted because it's not a critical failure — the LLM will handle gracefully)
           * Token migration: text-green-500 → text-positive for palette consistency.
           */}
          {t.status === "ok" ? (
            <Check className="h-3 w-3 text-positive shrink-0" aria-hidden="true" />
          ) : (
            <X className="h-3 w-3 text-muted-foreground shrink-0" aria-hidden="true" />
          )}
          {/*
           * WHY strikethrough + opacity-60:
           * - line-through signals "this phase is over, we're moving on"
           * - opacity-60 reduces visual weight so done tools recede behind running ones
           * - Stripping trailing "..." because "Searching documents" reads better than
           *   "~~Searching documents...~~" — the ellipsis implies "in progress"
           */}
          <span className="line-through opacity-60">
            {t.label.replace(/\.\.\.$/, "")}
          </span>
        </div>
      ))}
    </div>
  );
}
