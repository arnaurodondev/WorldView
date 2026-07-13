/**
 * features/chat/components/ChatComposer.tsx — Chat input composer.
 *
 * WHY THIS EXISTS (PLAN-0089 Wave K, Block E, T-17):
 *   The chat page's bottom input region previously lived inline inside
 *   `app/(app)/chat/page.tsx` (~lines 887–994). That made the page file
 *   ~1200 LOC and tangled keyboard handling + autocomplete + entity-
 *   context chrome + chip rail with thread-rail / message-list render
 *   logic. Block G slims the page; this is the extraction target.
 *
 *   The composer owns NO state of its own beyond focus + a forwarded
 *   imperative handle. The textarea value is fully controlled by the
 *   parent (via `value` / `onChange`) — that keeps the chat page's
 *   `input` state authoritative for `handleSend`, slash-command
 *   detection (`autocomplete.visible`), and the character counter.
 *
 *   DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §3 (composer).
 *
 * WHY "use client": owns a textarea ref + keyboard event handlers
 *   (Enter to send, Shift+Enter newline, Esc to cancel). Those only
 *   work on the client; "use client" opts the file out of server-
 *   component rendering so refs + onKeyDown bind to the DOM event loop.
 */

"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Send } from "lucide-react";
import { SlashCommandAutocomplete } from "@/components/chat/SlashCommandAutocomplete";
import type { SlashCommand } from "@/lib/chat/slash-commands";

// ── Props ─────────────────────────────────────────────────────────────────────

/** Entity-context strip shown above the composer (e.g. "Context: AAPL"). */
export interface ComposerEntityContext {
  readonly label: string;
}

/** Related-ticker chip — click pivots the next question to that ticker. */
export interface ComposerRelatedChip {
  readonly ticker: string;
  readonly onPick: () => void;
}

/** Slash-command autocomplete wiring; render only when `visible`. */
export interface ComposerAutocomplete {
  readonly visible: boolean;
  readonly query: string;
  readonly onPick: (cmd: SlashCommand) => void;
}

export interface ChatComposerProps {
  readonly value: string;
  readonly onChange: (next: string) => void;
  readonly onSend: () => void;
  /** Cancel an in-flight stream — also fires on Esc when streaming. */
  readonly onCancel?: () => void;
  readonly isStreaming: boolean;
  /** Falsy disables the Send button (e.g. no access token). Defaults true. */
  readonly canSend?: boolean;
  readonly entityContext?: ComposerEntityContext;
  readonly relatedChips?: readonly ComposerRelatedChip[];
  readonly autocomplete?: ComposerAutocomplete;
}

/** Imperative handle so parents can re-focus the textarea after chip clicks. */
export interface ChatComposerHandle {
  focus: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export const ChatComposer = forwardRef<ChatComposerHandle, ChatComposerProps>(
  function ChatComposer(props, ref): ReactNode {
    const {
      value,
      onChange,
      onSend,
      onCancel,
      isStreaming,
      canSend = true,
      entityContext,
      relatedChips,
      autocomplete,
    } = props;

    // WHY internal ref + imperative handle: we need direct DOM access for
    // focus() but parents shouldn't see the raw HTMLTextAreaElement.
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    const isSendDisabled = !value.trim() || isStreaming || !canSend;

    // Preserve the exact keymap from page.tsx so keyboard-driven analysts
    // experience no behaviour change after the lift-and-shift:
    //   Enter (no shift) → send
    //   Shift+Enter      → newline (default textarea behaviour)
    //   Esc while streaming → cancel
    function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): void {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
        return;
      }
      if (e.key === "Escape" && isStreaming && onCancel) {
        e.preventDefault();
        onCancel();
      }
    }

    const showChipRail = (relatedChips?.length ?? 0) > 0 && !autocomplete?.visible;

    return (
      // WHY border-t + bg-background + p-3: composer sits in a sticky
      // footer separated from the message list by a 1px terminal border;
      // 12px padding matches the chat surface rhythm.
      <div className="border-t border-border bg-background p-3">
        {entityContext && (
          <div className="mb-2 flex items-center gap-2 border-b border-border/40 pb-2">
            <span
              data-cell="composer-entity-context"
              className="rounded-[2px] bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary"
            >
              Context: {entityContext.label}
            </span>
            <span className="text-[10px] text-muted-foreground">
              questions will focus on this entity
            </span>
          </div>
        )}

        {isStreaming && onCancel && (
          // Centred "Stop generating" pill — analysts need a deterministic
          // cancel affordance for long-running answers.
          <div className="mb-2 flex justify-center">
            <Button
              size="sm"
              variant="outline"
              onClick={onCancel}
              data-cell="composer-stop-streaming"
              className="h-7 border-destructive/30 px-3 text-xs text-destructive hover:bg-destructive/10"
            >
              Stop generating
            </Button>
          </div>
        )}

        {showChipRail && (
          // Chip rail collapses when the autocomplete popover opens so the
          // two affordances never stack and crowd the textarea.
          <div className="mb-2 flex flex-wrap items-center gap-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/60">
              Related:
            </span>
            {relatedChips?.map((chip) => (
              <button
                key={chip.ticker}
                type="button"
                onClick={chip.onPick}
                title={`Add ${chip.ticker} to query`}
                data-cell="composer-related-chip"
                // tabular-nums keeps chip widths stable when tickers change length.
                className="rounded-[2px] border border-border/70 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-foreground transition-colors hover:border-primary/50 hover:text-primary"
              >
                {chip.ticker}
              </button>
            ))}
          </div>
        )}

        {autocomplete?.visible && (
          <SlashCommandAutocomplete
            query={autocomplete.query}
            onPick={autocomplete.onPick}
          />
        )}

        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about markets, companies, news…  Type / for commands. (Enter to send, Shift+Enter for newline)"
            rows={2}
            disabled={isStreaming}
            maxLength={2000}
            // text-[12px]: density bundle 2026-05-09 aligned the textarea
            // with the surrounding 11–12px terminal-density scale.
            className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-3 py-2 text-[12px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
            aria-label="Chat message input"
          />

          <Button
            onClick={onSend}
            disabled={isSendDisabled}
            data-cell="composer-send"
            className="h-10 w-10 shrink-0 bg-primary p-0 text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" strokeWidth={1.5} />
          </Button>
        </div>

        {value.length > 1500 && (
          // Counter only appears in the last quartile so it isn't noise
          // for short prompts.
          <p className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground">
            {value.length} / 2000
          </p>
        )}

        {/*
         * PERSISTENT PLATFORM DISCLAIMER (liability coverage)
         *
         * WHY IT LIVES HERE: the composer is the one region that is ALWAYS
         * mounted on the chat surface (empty state, mid-thread, and while
         * streaming), so a line rendered here is guaranteed to be visible on
         * every chat view without our having to duplicate it across the empty
         * state / message-list / footer. Placing it directly under the input
         * keeps it adjacent to the action the user just took (asking a
         * question) — the natural spot for a "this isn't advice" caveat.
         *
         * WHY IT IS SUBTLE: we deliberately reuse the smallest muted-caption
         * scale already used above (the char counter's `text-[10px]
         * text-muted-foreground`) so the notice reads as ambient chrome rather
         * than a modal/banner. It must be legally present, not attention-
         * grabbing. Colour comes from the `--muted-foreground` design token
         * (via Tailwind's `text-muted-foreground`), NOT a hardcoded hex — this
         * keeps it correct under the Midnight Pro dark theme and dodges the
         * known hsl(var()) no-paint bug that bites raw colour literals.
         *
         * `role="note"` + a stable `data-cell` give screen readers a landmark
         * and give tests/analytics a deterministic hook.
         */}
        <p
          role="note"
          data-cell="composer-disclaimer"
          className="mt-2 text-center text-[10px] leading-tight text-muted-foreground"
        >
          Worldview provides market intelligence for informational purposes only
          — not financial advice or a recommendation.
        </p>
      </div>
    );
  },
);
