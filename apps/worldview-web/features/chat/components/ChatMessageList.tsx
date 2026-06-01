/**
 * features/chat/components/ChatMessageList.tsx — Flat message column renderer.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-06):
 *   The legacy chat page rendered messages as `MessageBubble` (rounded
 *   chat-bubble shell, avatar, max-w-[70%]). Wave K replaces that consumer
 *   chat aesthetic with a Bloomberg-grade FLAT terminal layout: each turn
 *   spans the full column width, has a single-character role gutter
 *   (`U` / `A`), no avatar, no rounded shell, and a coloured accent rail
 *   only while streaming (see T-07 MessageTurn). This component is the
 *   container that walks the local message log + the in-flight streaming
 *   state and emits one `<MessageTurn>` per entry plus a trailing one for
 *   the streaming bubble.
 *
 *   The auto-scroll behaviour from the legacy page (smooth scroll to
 *   bottom on every token / new message) is preserved 1:1 — without it
 *   the user would have to manually drag the scrollbar during a long
 *   answer.
 *
 * WHY SlashTurn IS HANDLED HERE:
 *   The conversation log is a mixed list of `Message` and `SlashTurn`
 *   entries (the latter is a client-only rendered slash-command card).
 *   Centralising the `kind`-discrimination here means MessageTurn stays
 *   strictly typed against `Message` and never has to think about slash
 *   turns. SlashTurnBlock is the existing renderer; we keep it untouched.
 *
 * DATA SOURCE: pure prop forwarding from the page's `useChatStream` +
 *   TanStack query for the active thread. No fetch in this component.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §3.2 (message column)
 *   + §5 (flat turn layout).
 */

"use client";
// WHY "use client": owns a DOM ref (the auto-scroll anchor) and a
// useEffect that scrolls on update. Both browser-only.

import { useEffect, useRef } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { MessageTurn } from "@/features/chat/components/MessageTurn";
import { SlashTurnBlock } from "@/features/chat/components/SlashTurnBlock";
import type { LogEntry, StreamingMessage } from "@/features/chat/lib/types";
import type { ToolCallState } from "@/features/chat/components/ToolCallIndicator";
import type { Message } from "@/types/api";

interface ChatMessageListProps {
  /**
   * Mixed log of `Message` and `SlashTurn` entries. Owned by the page's
   * `useChatStream` — we never mutate it here.
   */
  readonly messages: LogEntry[];
  /**
   * Transient in-flight streaming bubble (or `null` when idle). When
   * non-null we render an additional `<MessageTurn isStreaming>` at the
   * bottom of the list — the streaming bubble looks like a finished turn
   * minus a few footer chips, which keeps the visual jump on completion
   * to a minimum.
   */
  readonly streaming: StreamingMessage | null;
  /**
   * Active tool-call entries from `useChatStream.activeTools`. Threaded
   * into the streaming turn's `ToolCallTray` (T-08).
   */
  readonly activeTools: ToolCallState[];
  /** Thread loading flag for the skeleton rows. */
  readonly threadLoading: boolean;
  /**
   * Optional follow-up click handler. Bubbles up from `FollowUpChips`
   * inside each `<MessageTurn>` — the page wires this to the composer's
   * "send immediately" handler.
   */
  readonly onFollowUp?: (suggestion: string) => void;
  /**
   * Optional empty-state slot rendered when `messages.length === 0` and
   * we are not streaming and not loading. The page uses this for the
   * starter-questions grid. Keeping it as a slot (not hard-coded here)
   * means the legacy starter logic in the page can stay until Block G
   * extracts ChatEmptyState (T-18).
   */
  readonly emptyState?: React.ReactNode;
}

/**
 * ChatMessageList — see file header.
 *
 * AUTO-SCROLL: we attach a hidden anchor div at the bottom of the list
 * and call `scrollIntoView({ behavior: 'smooth' })` whenever the message
 * count or the streaming text changes. The effect lives here (not in the
 * page) so the page no longer needs to know about scroll choreography.
 */
export function ChatMessageList({
  messages,
  streaming,
  activeTools,
  threadLoading,
  onFollowUp,
  emptyState,
}: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the bottom on every new message OR streaming token.
  // WHY both deps: token-level streaming fires only `streaming?.text` updates;
  // message-level history loads only fire `messages.length`. We want scroll
  // on either signal.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming?.text]);

  // Pre-compute whether we should render the "nothing yet" slot. We avoid
  // showing it during loading (skeletons cover that) or while a stream is
  // mid-flight (the streaming turn covers the empty case visually).
  const showEmptyState =
    !threadLoading && messages.length === 0 && !streaming;

  return (
    <ScrollArea className="flex-1 bg-background">
      {/* WHY flex-col gap-0: turns own their own internal spacing (the
          MessageTurn body uses `py-1` for the 24px row height). Using
          gap here would double the visual spacing and break the
          design-system 24/18/16 row-height contract. */}
      <div className="flex flex-col p-3">
        {threadLoading && (
          <div className="space-y-2" aria-label="Loading messages">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full rounded-[2px]" />
            ))}
          </div>
        )}

        {/* Empty state slot — the page passes the starter-questions grid. */}
        {showEmptyState ? emptyState : null}

        {/* The message log. SlashTurnBlock is kept verbatim from legacy. */}
        {messages.map((entry) => {
          if ("kind" in entry && entry.kind === "slash") {
            return <SlashTurnBlock key={entry.message_id} turn={entry} />;
          }
          const msg = entry as Message;
          return (
            <MessageTurn
              key={msg.message_id}
              turn={msg}
              onFollowUp={onFollowUp}
            />
          );
        })}

        {/* Streaming turn — only when a stream is in-flight. We project the
            transient StreamingMessage onto a synthetic `Message` so that
            MessageTurn does not need a parallel "streaming" prop path —
            the same renderer handles both, the only difference is the
            `isStreaming` flag that turns on the accent rail and replaces
            the latency value with a "streaming…" label inside
            MessageMetaStrip.

            WHY a synthetic Message (not a separate StreamingTurn component):
            keeps the visual transition seamless when the stream completes
            and the real Message replaces the synthetic one — same DOM
            tree, same selectors. The `data-testid="streaming-turn"`
            attribute lets T-23 Playwright assert against the running
            stream specifically. */}
        {streaming ? (
          <MessageTurn
            key="__streaming__"
            isStreaming
            activeTools={activeTools}
            intent={streaming.intent}
            initialStatus={streaming.initial_status}
            grounded={streaming.grounded}
            turn={{
              // Synthetic id — the real message_id arrives via the metadata
              // SSE event; if it does, useChatStream copies it onto
              // streaming.message_id which we forward here. Otherwise we
              // use the literal sentinel so React's diff doesn't keep
              // re-creating the node.
              message_id: streaming.message_id ?? "__streaming__",
              thread_id: "__streaming__",
              role: "assistant",
              content: streaming.text,
              created_at: new Date().toISOString(),
              citations: [],
              provider: streaming.provider,
              model: streaming.model,
              latency_ms: streaming.latency_ms,
              contradictions: streaming.contradictions,
            }}
          />
        ) : null}

        {/* Auto-scroll anchor. WHY a sentinel div (not just ScrollArea API):
            ScrollArea is a Radix wrapper without a direct "scroll to bottom"
            method; the sentinel is the canonical workaround. */}
        <div ref={endRef} />
      </div>
    </ScrollArea>
  );
}
