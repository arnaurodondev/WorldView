/**
 * components/intelligence/EntityChatPanel.tsx — Full-width entity-scoped chat
 * (PLAN-0074 Wave H T-H-06)
 *
 * WHY THIS EXISTS:
 * The intelligence page includes a collapsible chat panel at the bottom so
 * analysts can ask entity-specific questions without leaving the page. The
 * chat uses the extended useChatStream hook with entityId set to the anchor
 * entity, which routes to /api/v1/chat/entity-context — a RAG endpoint that
 * scopes retrieval to the entity's knowledge graph evidence.
 *
 * WHY anchorEntityId (not selectedEntityId):
 * The chat is scoped to the entity the analyst NAVIGATED to (the anchor),
 * not the entity they most recently CLICKED in the graph. This distinction
 * matters because:
 *   1. The analyst opened this page to research "Apple Inc." — the chat
 *      should answer questions about Apple, not Tim Cook just because
 *      they clicked his node.
 *   2. Changing the chat context on every node click would confuse ongoing
 *      multi-turn conversations — the thread would suddenly shift topic.
 *   3. Entity-specific RAG context (Apple's news, filings, KG relations)
 *      is what makes this chat valuable; scoping to Tim Cook would produce
 *      a much weaker, unrelated context.
 * Analysts who want to chat about Tim Cook can navigate to his intelligence page.
 *
 * WHY conversation_id in useState (session-only):
 * The conversation ID ties multi-turn messages into a coherent thread. It's
 * generated on first send and reused for the session. We do NOT persist it to
 * localStorage because entity-page chat sessions are exploratory and transient —
 * analysts don't expect to resume them later (unlike the main /chat page threads).
 * Session-only state is the simplest correct solution.
 *
 * WHY Enter to send (not button-only):
 * Finance analysts use keyboards almost exclusively. The Bloomberg Terminal sends
 * on Enter. Requiring a mouse click would break the keyboard-first workflow.
 * Shift+Enter preserves multi-line input (same as the main chat page).
 *
 * WHO USES IT: IntelligenceLayout full-width bottom row
 * DATA SOURCE: POST /api/v1/chat/entity-context (via useChatStream)
 */

"use client";
// WHY "use client": uses state, refs, and the SSE streaming hook.

import { useState, useRef, useCallback, useEffect, type KeyboardEvent } from "react";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { useAuth } from "@/hooks/useAuth";
import { useSelectedEntity } from "@/contexts/SelectedEntityContext";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronUp, ChevronDown, Send, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/api";
import type { LogEntry } from "@/features/chat/lib/types";

// ── Props ─────────────────────────────────────────────────────────────────────

interface EntityChatPanelProps {
  entityId: string; // anchor entity UUIDv7
}

// ── Constants ─────────────────────────────────────────────────────────────────

const COLLAPSED_HEIGHT = 200; // px — default "compact" height
const EXPANDED_HEIGHT = 400;  // px — analyst "focused" height

// ── Component ─────────────────────────────────────────────────────────────────

export function EntityChatPanel({ entityId: _entityId }: EntityChatPanelProps) {
  // WHY _entityId (prefixed): the prop is accepted for API contract clarity
  // (callers should pass the anchor entity ID), but internally we read
  // anchorEntityId from SelectedEntityContext to guarantee we always use the
  // anchor — even if the prop origin changes. The _ prefix satisfies the
  // no-unused-vars ESLint rule for intentionally-unused destructured args.
  const { accessToken } = useAuth();
  const { anchorEntityId } = useSelectedEntity();

  // ── Chat panel state ──────────────────────────────────────────────────────

  // WHY collapsed by default: the panel starts compact so it doesn't push
  // the three analysis columns off-screen on shorter viewports.
  const [expanded, setExpanded] = useState(false);

  // WHY input state here (not in useChatStream):
  // useChatStream owns the streaming/message state. The input value is purely
  // a UI concern — managed at the component level so it can be cleared on send.
  const [input, setInput] = useState("");

  // ── Thread management ─────────────────────────────────────────────────────

  // WHY useState for conversation_id:
  // The conversation ID is session-only (see module comment). useState persists
  // it across re-renders (so multi-turn messages stay in the same thread) but
  // discards it when the user navigates away (no persistence to localStorage).
  const [conversationId, setConversationId] = useState<string | null>(null);

  // ── Scroll ref ────────────────────────────────────────────────────────────
  // WHY ref (not state): we call scrollIntoView() for UX, not for render logic.
  // A ref mutation never triggers re-renders — appropriate for scroll position.
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── useChatStream — extended with entityId (A-3 ADR) ─────────────────────
  const {
    localMessages,
    streaming,
    chatError,
    isStreaming,
    send,
  } = useChatStream({
    accessToken,
    activeThreadId: conversationId,
    setActiveThreadId: setConversationId,
    // WHY no-op refetchThreads: the entity chat panel is not connected to the
    // thread list sidebar (which lives on the /chat page). Passing a no-op
    // satisfies the hook contract without triggering unnecessary queries.
    refetchThreads: () => {},
    // WHY anchorEntityId (not selectedEntityId): see module comment — chat
    // is always scoped to the anchor entity, never the selected node.
    entityId: anchorEntityId,
  });

  // ── Auto-scroll to bottom when new messages arrive ────────────────────────
  // WHY useEffect on [localMessages, streaming]: both trigger new content in
  // the message list. We want the latest content visible without the analyst
  // manually scrolling every time.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, streaming]);

  // ── Keyboard handler ──────────────────────────────────────────────────────

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // WHY Enter sends (not a form submit):
      // Finance terminal convention — same as Bloomberg, same as the main
      // /chat page. The textarea captures Enter to prevent default newline.
      // Shift+Enter passes through to allow multi-line messages.
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (input.trim() && !isStreaming) {
          void send(input.trim());
          setInput("");
        }
      }
    },
    [input, isStreaming, send],
  );

  // ── Send handler ──────────────────────────────────────────────────────────

  const handleSend = useCallback(() => {
    if (input.trim() && !isStreaming) {
      void send(input.trim());
      setInput("");
    }
  }, [input, isStreaming, send]);

  // ── Render ────────────────────────────────────────────────────────────────

  const panelHeight = expanded ? EXPANDED_HEIGHT : COLLAPSED_HEIGHT;

  return (
    <div
      className="flex flex-col bg-background border-t border-border transition-all duration-200"
      style={{ height: panelHeight }}
      aria-label="Entity-scoped chat panel"
    >
      {/* ── Panel header ──────────────────────────────────────────────────── */}
      <div className="flex-none flex items-center justify-between px-3 py-1.5 border-b border-border/50">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.5} />
          <span className="text-[11px] font-mono font-medium uppercase tracking-wider text-muted-foreground">
            Chat
          </span>
          {/* WHY entity name in header: confirms which entity the chat is scoped to.
              Analysts need to know if they're chatting about Apple vs Tim Cook. */}
          <span className="text-[11px] font-mono text-muted-foreground/60 truncate max-w-[200px]">
            · {anchorEntityId}
          </span>
        </div>

        {/* Expand / collapse toggle */}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-label={expanded ? "Collapse chat panel" : "Expand chat panel"}
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" strokeWidth={1.5} />
          ) : (
            <ChevronUp className="h-4 w-4" strokeWidth={1.5} />
          )}
        </button>
      </div>

      {/* ── Message list ──────────────────────────────────────────────────── */}
      <ScrollArea className="flex-1 px-3 py-2">
        {localMessages.length === 0 && !streaming && (
          <p className="text-[11px] text-muted-foreground font-mono text-center py-4">
            Ask about {anchorEntityId}…
          </p>
        )}

        {/* Message bubbles */}
        {localMessages.map((entry: LogEntry) => {
          // WHY type narrowing: LogEntry can be a Message or SlashTurn.
          // We only render Message entries here; SlashTurn is a different structure.
          if (!("role" in entry)) return null;
          const msg = entry as Message;
          const isUser = msg.role === "user";

          return (
            <div
              key={msg.message_id}
              className={cn(
                "flex mb-2",
                isUser ? "justify-end" : "justify-start",
              )}
            >
              <div
                className={cn(
                  "rounded-[2px] px-2.5 py-1.5 text-[11px] font-sans max-w-[85%] leading-relaxed",
                  isUser
                    ? // WHY amber background for user: primary color identifies
                      // the analyst's input. Matches the Bloomberg-terminal convention
                      // of highlighting user actions in amber.
                      "bg-primary/20 text-primary ml-auto"
                    : "bg-muted/60 text-foreground/90",
                )}
              >
                {msg.content}

                {/* Source chips on assistant messages */}
                {!isUser && msg.citations && msg.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5 pt-1 border-t border-border/30">
                    {msg.citations.slice(0, 4).map((c, i) => (
                      <span
                        key={i}
                        className="inline-block rounded-[2px] px-1 py-0.5 bg-muted text-muted-foreground text-[9px] font-mono"
                        title={c.title ?? ""}
                      >
                        {c.source ?? "src"}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Streaming bubble */}
        {streaming && (
          <div className="flex justify-start mb-2">
            <div className="rounded-[2px] px-2.5 py-1.5 text-[11px] font-sans max-w-[85%] bg-muted/60 text-foreground/90 leading-relaxed">
              {streaming.text || (
                // WHY animate-pulse + empty text: shows "thinking" state while
                // the first token hasn't arrived yet (LLM is still processing).
                <span className="inline-block w-3 h-3 rounded-full bg-muted-foreground animate-pulse" />
              )}
            </div>
          </div>
        )}

        {/* Error message */}
        {chatError && (
          <div className="mb-2 rounded-[2px] border border-destructive/40 bg-destructive/10 px-2.5 py-1.5">
            <p className="text-[11px] font-mono text-destructive">{chatError}</p>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </ScrollArea>

      {/* ── Input row ─────────────────────────────────────────────────────── */}
      <div className="flex-none flex items-end gap-2 px-3 py-2 border-t border-border/50">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about this entity… (Enter to send, Shift+Enter for newline)"
          className={cn(
            "flex-1 resize-none rounded-[2px] bg-muted/40 border border-border/60",
            "px-2.5 py-1.5 text-[11px] font-mono text-foreground",
            "placeholder:text-muted-foreground/60",
            "focus:outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30",
            "min-h-[36px] max-h-[72px]",
            "transition-colors",
          )}
          rows={1}
          disabled={isStreaming}
          aria-label="Chat input"
        />
        <Button
          size="sm"
          onClick={handleSend}
          // WHY disabled when empty: avoids empty API calls. isStreaming guard
          // prevents double-submitting while a response is arriving.
          disabled={!input.trim() || isStreaming}
          className="h-9 px-3 shrink-0"
          aria-label="Send message"
        >
          <Send className="h-3.5 w-3.5" strokeWidth={1.5} />
        </Button>
      </div>
    </div>
  );
}
