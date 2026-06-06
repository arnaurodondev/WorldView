/**
 * features/chat/components/ChatEmptyState.tsx — Chat panel empty state.
 *
 * WHY THIS EXISTS (PLAN-0089 Wave K, Block E, T-18):
 *   When no thread is selected, the right-hand chat panel shows a
 *   centred welcome with portfolio-scoped starter prompts and a
 *   "New conversation" CTA. Previously this was ~50 LOC of inline JSX
 *   inside `app/(app)/chat/page.tsx`; extracting it shrinks the page
 *   file and keeps the empty-state design behind a single import.
 *
 *   DESIGN: Bloomberg COMMAND BAR welcome style — a small two-line
 *   label/description hierarchy ("Analyst Intelligence" → scope copy)
 *   followed by clickable starter prompt cards. The starter prompts
 *   pre-fill the input on click; the parent owns input state and
 *   creates the new thread after the click.
 *
 *   We deliberately do NOT compose `<EmptyState>` (the F1 primitive at
 *   `components/primitives/EmptyState.tsx`). That primitive renders a
 *   single status row with a copyKey-driven dictionary lookup; the
 *   chat welcome needs a 2-column starter grid + named CTA that don't
 *   fit the EmptyState row contract. A hand-rolled terminal-style
 *   empty matches the design doc §3 better (see 10-chat-ai.md).
 *
 * WHY "use client": the starter-prompt buttons own onClick handlers
 *   that mutate parent React state; client-side only.
 */

"use client";

import type { ReactNode } from "react";
import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ChatEmptyStateProps {
  /**
   * Starter prompts shown as a 2-column grid. Parent passes the
   * portfolio-scoped list (PLAN-0071 P2C-2). Omit to render only the
   * welcome strapline + CTA (no prompts).
   */
  readonly starters?: readonly string[];
  /**
   * Click handler for a starter prompt — parent typically sets `input`
   * to the prompt text and then calls `handleNewChat()`.
   */
  readonly onPickStarter?: (prompt: string) => void;
  /** "New conversation" button handler. Required — the CTA is always shown. */
  readonly onNewChat: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChatEmptyState(props: ChatEmptyStateProps): ReactNode {
  const { starters, onPickStarter, onNewChat } = props;
  const hasStarters = (starters?.length ?? 0) > 0;

  return (
    // WHY p-3 (was p-4 originally): the empty-state welcome sits inside
    // an already-bounded panel; 12 px padding keeps the welcome text
    // close to the surrounding panel chrome instead of floating in 16 px
    // ports. flex-1 lets the parent grow this region to fill the panel.
    <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-background p-3 text-center">
      <div className="space-y-1">
        {/* Strapline + description pair — Bloomberg COMMAND BAR welcome
            style: short imperative label, then scope clarification. */}
        <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.10em] text-muted-foreground">
          Analyst Intelligence
        </p>
        <p className="max-w-[280px] text-[11px] leading-relaxed text-muted-foreground">
          Research-grade Q&amp;A on earnings, SEC filings, macro, and your
          portfolio — grounded in real source documents, not hallucination.
        </p>
      </div>

      {hasStarters && (
        // 2-column grid of starter prompts. The pre-fill flow gives
        // analysts a low-friction way to discover the kinds of questions
        // the system answers well, without typing a single character.
        <div className="mt-1 grid w-full max-w-[440px] grid-cols-2 gap-1.5">
          {starters?.map((prompt, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onPickStarter?.(prompt)}
              data-cell="chat-empty-starter"
              className="rounded-[2px] border border-border bg-card p-2.5 text-left text-[10px] leading-relaxed text-foreground hover:border-primary/40 hover:bg-muted/40 transition-colors duration-0"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      <Button
        size="sm"
        onClick={onNewChat}
        data-cell="chat-empty-new"
        className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
      >
        <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
        New conversation
      </Button>
    </div>
  );
}
