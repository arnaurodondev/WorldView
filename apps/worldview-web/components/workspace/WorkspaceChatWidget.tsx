/**
 * WorkspaceChatWidget — embedded streaming chat for workspace chat panels
 *
 * WHY THIS EXISTS: The full chat page needs full-page width for the thread list
 * sidebar + message area. In a workspace panel (~400px wide), only the message
 * area + input matters. This widget is a slimmed-down version: no thread list,
 * single ephemeral session, compact 11px message bubbles, 36px input bar.
 *
 * WHY EPHEMERAL (no thread persistence): Workspace chat is for quick, in-context
 * questions while monitoring other panels — "what's driving AAPL down?", "summarise
 * the last 3 earnings calls". These are transient queries, not research sessions
 * that need to be saved. Thread persistence would add UI complexity without value.
 *
 * WHY SSE via streamChat (not useQuery): Chat responses are streaming — the model
 * outputs tokens incrementally. useQuery resolves once (when the promise settles).
 * fetch + ReadableStream lets us append tokens to the AI message in real time.
 *
 * WHO USES IT: workspace/page.tsx — rendered inside the "chat" panel type.
 * DATA SOURCE: S9 POST /api/v1/chat/stream (SSE streaming response)
 * DESIGN REFERENCE: PRD-0031 §12b Chat enhancements, §0 Terminal CLI Quality Standard
 */

"use client";
// WHY "use client": uses useState (messages, input, streaming flag), useRef
// (scroll-to-bottom, reader abort), and browser ReadableStream (SSE reading).

import { useState, useRef, useEffect, useCallback } from "react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

// ── Types ──────────────────────────────────────────────────────────────────────

type MessageRole = "user" | "assistant";

interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  /** True while the AI is still streaming tokens for this message */
  streaming: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** Starter question visible in empty state to give users a jumping-off point */
const STARTER_QUESTIONS = [
  "What's driving market movement today?",
  "Summarise recent AAPL earnings",
  "What sectors are outperforming?",
];

/** Fake thread ID for the ephemeral workspace session.
 * WHY a fixed UUID (not crypto.randomUUID()): the streamChat request requires
 * a thread_id. Using a constant means all workspace chat messages share one
 * ephemeral thread for this browser session — acceptable for the workspace context.
 * A full thread is created only on the dedicated Chat page. */
const WORKSPACE_THREAD_ID = "workspace-ephemeral";

/** Maximum messages to keep in view (oldest are dropped above this limit) */
const MAX_MESSAGES = 20;

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * WorkspaceChatWidget — minimal SSE chat embedded in a workspace panel.
 * Replaces WorkspacePlaceholder for the "chat" panel type.
 */
export function WorkspaceChatWidget() {
  const { accessToken } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // WHY abortRef: SSE streaming uses a ReadableStream reader. Storing the reader
  // lets us cancel it if the user navigates away while a response is streaming —
  // prevents orphaned background network activity.
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  // ── Auto-scroll to bottom when new message content arrives ────────────────
  useEffect(() => {
    if (scrollRef.current) {
      // WHY scrollTop = scrollHeight: always pins to the last message. This is
      // the standard chat scroll behaviour — users see new tokens as they arrive.
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // ── Cancel any active stream on unmount ───────────────────────────────────
  useEffect(() => {
    return () => {
      // WHY cancel on unmount: if the workspace panel is closed while streaming,
      // the reader would keep consuming bytes with nowhere to put them.
      readerRef.current?.cancel().catch(() => {/* ignore cancel errors */});
    };
  }, []);

  // ── Handle send ───────────────────────────────────────────────────────────
  const handleSend = useCallback(async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;

    setInput("");
    setIsStreaming(true);

    // Append user message
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      streaming: false,
    };

    // Append empty AI message that will be filled token-by-token
    const aiMsgId = `ai-${Date.now()}`;
    const aiMsg: ChatMessage = {
      id: aiMsgId,
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => {
      // WHY slice(-MAX_MESSAGES + 2): cap history at MAX_MESSAGES total.
      // Slice from the back so the newest messages are always visible.
      const kept = prev.slice(-(MAX_MESSAGES - 2));
      return [...kept, userMsg, aiMsg];
    });

    try {
      const stream = await createGateway(accessToken).streamChat({
        question: trimmed,
        thread_id: WORKSPACE_THREAD_ID,
      });

      if (!stream) {
        throw new Error("No stream returned from streamChat");
      }

      const reader = stream.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();

      // Read SSE chunks and append tokens to the AI message
      let done = false;
      while (!done) {
        const result = await reader.read();
        done = result.done;
        if (result.value) {
          // WHY TextDecoder: ReadableStream yields Uint8Array; we need the text.
          // streaming=true so we can keep accumulating; mark false when done.
          const chunk = decoder.decode(result.value, { stream: true });
          // Parse SSE format: "data: {token}\n\n"
          const lines = chunk.split("\n");
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const payload = line.slice(6).trim();
              if (payload && payload !== "[DONE]") {
                try {
                  const parsed = JSON.parse(payload) as { token?: string; content?: string };
                  const token = parsed.token ?? parsed.content ?? "";
                  if (token) {
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === aiMsgId
                          ? { ...m, content: m.content + token }
                          : m
                      )
                    );
                  }
                } catch {
                  // Non-JSON SSE line (e.g., keep-alive comment) — skip
                }
              }
            }
          }
        }
      }
    } catch (err) {
      // WHY replace with error message (not throw): the panel should stay usable
      // after a failed stream. Show the error inline in the AI message position.
      const errorText = err instanceof Error ? err.message : "Stream error";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsgId
            ? { ...m, content: `Error: ${errorText}`, streaming: false }
            : m
        )
      );
    } finally {
      // Mark AI message as done streaming regardless of success or error
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsgId ? { ...m, streaming: false } : m
        )
      );
      readerRef.current = null;
      setIsStreaming(false);
      // WHY re-focus: after streaming completes, focus the input so the user
      // can immediately type a follow-up question without clicking.
      inputRef.current?.focus();
    }
  }, [accessToken, isStreaming]);

  // ── Handle Enter key ──────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSend(input);
      }
    },
    [handleSend, input]
  );

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    // WHY flex flex-col h-full: the workspace panel card controls outer height.
    // This widget fills it completely: messages scroll in the middle, input is
    // pinned at the bottom. Never use fixed heights here.
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Message area ────────────────────────────────────────────────── */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-auto p-2 space-y-1.5"
        aria-live="polite"
        aria-label="Chat messages"
      >
        {messages.length === 0 ? (
          // ── Empty state: starter questions ─────────────────────────────
          // WHY starter questions instead of centered icon: terminal empty states
          // (§0.5) are functional — they let the user do something immediately.
          // Showing 3 clickable question templates is more useful than "Ask me
          // anything" placeholder text with a chat bubble icon.
          <div className="space-y-1 pt-1">
            <p className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              QUICK QUERIES
            </p>
            {STARTER_QUESTIONS.map((q) => (
              <button
                key={q}
                onClick={() => void handleSend(q)}
                disabled={isStreaming}
                // WHY text-left + full width: makes the entire row clickable,
                // not just the text. Standard terminal interactive row convention.
                className="w-full text-left rounded-[2px] border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-colors duration-0 disabled:opacity-40"
              >
                {q}
              </button>
            ))}
          </div>
        ) : (
          // ── Message bubbles ─────────────────────────────────────────────
          messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}
      </div>

      {/* ── Input bar ───────────────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border flex items-center gap-1.5 px-2 py-1.5">
        <input
          ref={inputRef}
          type="text"
          placeholder="Ask anything…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          aria-label="Chat input"
          // WHY h-7 (28px): §0.7 compact input inside a filter/tool bar.
          // NOT h-9 (36px) — that size is for the main chat page input, not workspace.
          className="flex-1 h-7 rounded-[2px] border border-border bg-background px-2 text-[11px] text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary focus-visible:ring-offset-0 disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
        />
        <button
          onClick={() => void handleSend(input)}
          disabled={isStreaming || !input.trim()}
          aria-label="Send message"
          // WHY w-7 h-7: square button matches the input height for visual alignment.
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] border border-border bg-muted text-[10px] text-muted-foreground hover:bg-muted/60 hover:text-foreground disabled:opacity-40 transition-colors duration-0"
        >
          {/* WHY → instead of SVG icon: terminal aesthetic, minimal icon overhead */}
          →
        </button>
      </div>
    </div>
  );
}

// ── MessageBubble sub-component ───────────────────────────────────────────────

/**
 * MessageBubble — renders a single chat message.
 *
 * WHY right-align user / left-align AI: standard chat convention that
 * institutional traders recognise from Bloomberg chat and Slack. The
 * visual split also makes it easy to scan the conversation flow.
 *
 * WHY text-[11px]: §0.1 data values use 11px. Chat in a workspace panel
 * is dense — 13px body text would fit fewer messages on screen.
 */
function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        // WHY max-w-[85%]: prevents bubbles from spanning the full panel width.
        // 85% leaves a visible gutter on the opposite side, reinforcing the
        // left/right conversation rhythm.
        className={`max-w-[85%] rounded-[2px] px-2 py-1 text-[11px] leading-relaxed ${
          isUser
            ? "bg-primary/15 text-foreground"   // user: subtle yellow tint
            : "bg-muted/30 text-foreground"      // AI: subtle muted tint
        }`}
      >
        {message.content || (message.streaming ? (
          // WHY inline cursor character (not TypingIndicator): avoids importing the full
          // TypingIndicator component from the chat page, keeping bundle size smaller.
          // WHY no animate-pulse: Bloomberg-terminal standard — no pulsing animations on
          // interactive surfaces (§0 mandate). The static cursor character still reads
          // as "awaiting response" without animating.
          <span className="text-muted-foreground">▋</span>
        ) : null)}
      </div>
    </div>
  );
}
