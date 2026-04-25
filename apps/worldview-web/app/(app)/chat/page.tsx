/**
 * app/(app)/chat/page.tsx — Intelligence / Chat page
 *
 * WHY THIS EXISTS: Full-featured RAG (Retrieval-Augmented Generation) chat for
 * research-grade market intelligence queries. Unlike the AskAiPanel floating window
 * (single-shot questions), this page maintains persistent conversation threads so
 * analysts can build on prior context ("Earlier you said NVDA had a margin headwind.
 * How does that compare to AMD's guidance?"). Thread history persists across sessions.
 *
 * WHY TWO-COLUMN LAYOUT (thread list | chat):
 * Mirrors the established UX pattern from Slack, Claude, and Bloomberg's Chat panel.
 * Analysts create multiple focused threads (AAPL earnings, Fed expectations, sector
 * rotation thesis) and switch between them without losing context.
 *
 * WHY SSE STREAMING (not request/response):
 * LLM responses take 2–8 seconds to generate. Streaming tokens to the UI creates
 * the "typewriter" effect — users start reading before generation completes.
 * For a finance terminal, perceived latency matters enormously.
 *
 * WHY POST + fetch() (not EventSource):
 * The SSE endpoint requires a POST body { question, thread_id }.
 * EventSource only supports GET requests and cannot send a POST body.
 * We use fetch() + response.body.getReader() to consume the SSE stream manually.
 *
 * WHY crypto.randomUUID() for new threads (not POST first):
 * We optimistically assign a thread_id client-side so streaming can begin
 * immediately without a round-trip to create the thread first. The first POST
 * /chat/stream creates the thread server-side if it doesn't exist.
 *
 * WHO USES IT: Authenticated users at /chat
 * DATA SOURCES:
 *   GET  /api/v1/threads          — thread list
 *   GET  /api/v1/threads/:id      — thread with full message history
 *   POST /api/v1/chat/stream      — SSE streaming response
 * DESIGN REFERENCE: PRD-0028 §6.5 Chat page (layout §6.3, spec §6.5.9)
 */

"use client";
// WHY "use client": Heavy interactive state — streaming SSE via fetch + ReadableStream,
// message list with auto-scroll, thread selection, keyboard shortcuts (Enter to send,
// Shift+Enter for newline). All of these require browser APIs unavailable in Server
// Components. Rendering happens on the client to keep the streaming state local.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { MessageSquare, Plus, Send, Trash2, Bot } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { safeExternalUrl, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Thread, Message, Citation } from "@/types/api";

// ── Local types ───────────────────────────────────────────────────────────────

/**
 * StreamingMessage — transient in-flight bubble displayed while SSE tokens arrive.
 * Once the stream completes (either [DONE] sentinel or reader exhaustion), the
 * accumulated text becomes a proper Message in the messages array.
 */
interface StreamingMessage {
  /** Tokens accumulated so far from the SSE stream */
  text: string;
  /** Whether the stream is still open (controls blinking cursor visibility) */
  active: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * WHY PLACEHOLDER_THREAD_TITLE: When a thread has no title (S9 sets it to null
 * until the first message is processed by the LLM), show a human-readable label.
 */
const PLACEHOLDER_THREAD_TITLE = "New conversation";

/**
 * STARTER_QUESTIONS — pre-filled question cards shown when a thread has no messages.
 *
 * WHY starter questions: empty-thread state is a common UX dead zone — users
 * don't know what to ask first. Pre-seeded cards reduce blank-page anxiety and
 * guide traders toward high-value research questions. [TICKER] is replaced at
 * render time with the entity ticker from the URL param (if available).
 */
const STARTER_QUESTIONS = [
  "What are the key risks for [TICKER] next quarter?",
  "Compare MSFT and GOOGL cloud revenue growth over 4 quarters",
  "Summarize [TICKER]'s latest earnings call",
  "Recent insider transactions and what they signal",
  "What analyst consensus shows for [TICKER] in 2026?",
  "Search SEC filings for 'supply chain' risk exposure",
] as const;

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * TypingIndicator — animated three-dot bubble shown while SSE stream is active.
 * Finance-grade polish: indicates the LLM is generating, not that the network stalled.
 */
function TypingIndicator() {
  return (
    // WHY bg-muted: assistant messages use muted background (user messages use primary/10)
    <div className="flex max-w-[70%] items-end gap-2 self-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="rounded-[2px] bg-muted px-4 py-3">
        {/* Three animated dots — the staggered animation conveys "thinking" */}
        <div className="flex gap-1" aria-label="AI is generating a response">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

/**
 * CITATION_ICONS — maps citation source type to a display icon.
 *
 * WHY source type icons: visual icons let traders instantly recognise the
 * nature of a citation (SEC filing vs news vs earnings call) without reading
 * the source string. This is especially useful when 3–5 citations appear
 * below an assistant message and the trader scans for the most authoritative one.
 */
const CITATION_ICONS: Record<string, string> = {
  sec: "📄",
  news: "📰",
  earnings: "📊",
  knowledge_graph: "🕸",
};

/**
 * getCitationIcon — infer a citation icon from source or title heuristics.
 * WHY heuristics: Citation.source is a human-readable string like "Reuters",
 * not a structured type enum. We fall back to title-keyword matching when
 * source doesn't match a known key.
 */
function getCitationIcon(cite: Citation): string {
  const src = cite.source.toLowerCase();
  if (src.includes("sec") || src.includes("edgar") || src.includes("filing")) {
    return CITATION_ICONS.sec ?? "📄";
  }
  if (src.includes("earning") || src.includes("transcript")) {
    return CITATION_ICONS.earnings ?? "📊";
  }
  if (src.includes("knowledge") || src.includes("graph")) {
    return CITATION_ICONS.knowledge_graph ?? "🕸";
  }
  // Title heuristics for news citations
  const title = (cite.title ?? "").toLowerCase();
  if (title.includes("10-k") || title.includes("10-q") || title.includes("8-k")) {
    return CITATION_ICONS.sec ?? "📄";
  }
  return CITATION_ICONS.news ?? "📰";
}

/**
 * CitationList — renders source citations below assistant messages.
 * WHY show citations: RAG responses cite the exact articles the LLM used for
 * its answer. Analysts can click through to verify the primary source — critical
 * for finance where accuracy of sourcing matters legally.
 *
 * Wave 7 enhancement: each citation now shows a type icon + source + title + match%.
 */
function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((cite, i) => (
        <a
          key={cite.article_id}
          href={safeExternalUrl(cite.url)}
          target="_blank"
          rel="noopener noreferrer"
          // WHY primary/10 border primary/30: subtle but distinguishable citation pills.
          // hover:bg-primary/20 on dark bg gives clear affordance without aggressive color.
          className="inline-flex items-center gap-1 rounded-[2px] border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20"
          title={`${cite.source} — relevance: ${(cite.relevance_score * 100).toFixed(0)}%`}
        >
          {/* WHY superscript index: matches academic citation convention analysts recognise */}
          <sup className="font-mono text-[9px]">[{i + 1}]</sup>
          {/* Type icon — communicates SEC/news/earnings source at a glance */}
          <span aria-hidden="true">{getCitationIcon(cite)}</span>
          {/* Source name — abbreviated to fit pill width */}
          <span className="font-mono text-[9px] text-primary/70">{cite.source}</span>
          {/* Title — truncated */}
          <span className="max-w-[140px] truncate">{cite.title}</span>
          {/* Match % — how relevant the citation was to the question */}
          {/* WHY show match%: traders care about source reliability; a 90% match
              means the LLM used this article heavily vs a 20% tangential reference */}
          <span className="font-mono text-[9px] text-primary/60">
            {(cite.relevance_score * 100).toFixed(0)}%
          </span>
        </a>
      ))}
    </div>
  );
}

/**
 * MessageBubble — renders a single chat message with role-specific styling.
 * user messages: right-aligned, bg-primary/10
 * assistant messages: left-aligned, bg-muted + optional citations
 */
function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div
      // WHY flex-col + items-end/start: aligns the entire bubble (text + citations)
      // to the correct side before aligning the inner row horizontally.
      className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={`flex max-w-[70%] items-end gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}
      >
        {/* Avatar icon — bot icon for assistant, hidden for user to save space */}
        {!isUser && (
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
            <Bot className="h-3.5 w-3.5 text-primary" />
          </div>
        )}

        <div
          // WHY rounded-[2px]: terminal design uses uniform 2px radius; no consumer-app
          // asymmetric corner overrides (rounded-br-sm/rounded-bl-sm were dropped — at
          // the 2px scale, the distinction is imperceptible and adds visual complexity).
          className={`rounded-[2px] px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? // User bubble: right-aligned, amber tint
                "bg-primary/10 text-foreground"
              : // Assistant bubble: left-aligned, muted background
                "bg-muted text-foreground"
          }`}
        >
          {/*
           * WHY <pre> not a Markdown library:
           * The MVP requirement says "render as <pre> wrapped text".
           * Adding react-markdown adds 38 KB to the bundle — deferred to a later wave.
           * pre + whitespace-pre-wrap: preserves newlines and indentation from the LLM
           * output without needing full Markdown parsing.
           */}
          <pre className="whitespace-pre-wrap font-sans text-sm">{message.content}</pre>

          {/* WHY font-mono on timestamp: timestamps are data, not prose */}
          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>

      {/* Citations appear below assistant bubbles only */}
      {!isUser && message.citations.length > 0 && (
        <div className={`max-w-[70%] ${!isUser ? "ml-9" : ""}`}>
          <CitationList citations={message.citations} />
        </div>
      )}
    </div>
  );
}

/**
 * StreamingBubble — the in-flight assistant bubble shown while SSE tokens arrive.
 * Displays the accumulated text and a blinking cursor while `active` is true.
 * WHY separate from MessageBubble: streaming text is not yet a Message (no message_id,
 * no created_at, no citations). We avoid mutating the messages array mid-stream.
 */
function StreamingBubble({ streaming }: { streaming: StreamingMessage }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex max-w-[70%] items-end gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20">
          <Bot className="h-3.5 w-3.5 text-primary" />
        </div>
        <div className="rounded-[2px] bg-muted px-4 py-3 text-sm leading-relaxed">
          <pre className="whitespace-pre-wrap font-sans text-sm">{streaming.text}</pre>
          {/* Blinking cursor: visible while stream is active, hidden once done */}
          {streaming.active && (
            <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main page component ───────────────────────────────────────────────────────

export default function ChatPage() {
  const { accessToken } = useAuth();

  // ── Entity context from URL param ─────────────────────────────────────────
  // WHY useSearchParams: the instrument detail page navigates to /chat?entity_id=XXX
  // to pre-load AI context so questions auto-focus on the selected entity.
  const searchParams = useSearchParams();
  const entityIdFromUrl = searchParams.get("entity_id");

  // WHY entityTicker: we use the entity_id as-is for the context badge since
  // a gateway lookup for ticker would require additional async complexity.
  // A future wave can enrich this with a getEntity() call.
  const [entityTicker] = useState<string | null>(entityIdFromUrl);

  // ── Thread list state ──────────────────────────────────────────────────────

  /** Currently selected thread_id. null = no thread selected yet. */
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);

  /**
   * Locally accumulated messages for the active thread.
   * WHY local state (not just TanStack Query cache): streaming tokens arrive
   * one-by-one and need to update the UI at ~50 ms granularity. Mutating the
   * TanStack Query cache at that rate would cause excessive re-renders. We load
   * the initial history from the query cache, then track new messages locally.
   */
  const [localMessages, setLocalMessages] = useState<Message[]>([]);

  /** Transient streaming state for the in-flight SSE bubble */
  const [streaming, setStreaming] = useState<StreamingMessage | null>(null);

  /** Input textarea value */
  const [input, setInput] = useState("");

  /** Error message displayed in the chat area */
  const [chatError, setChatError] = useState<string | null>(null);

  // ── Refs ───────────────────────────────────────────────────────────────────

  /**
   * WHY useRef for the AbortController: SSE reading is async imperative work.
   * Storing the controller in a ref lets us call abort() from the Cancel button
   * without triggering re-renders on each stream chunk.
   */
  const abortRef = useRef<AbortController | null>(null);

  /**
   * WHY useRef for scroll target: We imperatively scroll to the bottom when
   * new messages arrive. Storing the DOM node in a ref is the correct pattern
   * for imperative DOM operations in React (not state).
   */
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

  /**
   * Thread list query — fetches all threads for the sidebar.
   * WHY staleTime 30s: thread titles change rarely; avoid hammering S9 while
   * the user is actively chatting.
   */
  const {
    data: threads,
    isLoading: threadsLoading,
    error: threadsError,
    refetch: refetchThreads,
  } = useQuery<Thread[]>({
    queryKey: ["threads", accessToken],
    queryFn: () => createGateway(accessToken).getThreads(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  /**
   * Active thread query — loads the message history when a thread is selected.
   * WHY disabled when no activeThreadId: prevents a useless request on initial load.
   */
  const {
    data: activeThread,
    isLoading: threadLoading,
  } = useQuery<Thread>({
    queryKey: ["thread", activeThreadId, accessToken],
    queryFn: () => createGateway(accessToken).getThread(activeThreadId!),
    enabled: !!accessToken && !!activeThreadId,
    staleTime: 0, // WHY staleTime 0: always fresh — new messages may have arrived
  });

  // ── Effects ────────────────────────────────────────────────────────────────

  /**
   * Sync activeThread messages into localMessages when the thread query succeeds.
   * WHY conditional: only update if the thread is the one we're displaying AND
   * we are not mid-stream (to avoid overwriting streaming tokens with stale data).
   */
  useEffect(() => {
    if (activeThread && activeThread.thread_id === activeThreadId && !streaming) {
      setLocalMessages(activeThread.messages);
    }
  }, [activeThread, activeThreadId, streaming]);

  /**
   * Scroll to bottom whenever messages update or a streaming token arrives.
   * WHY scrollIntoView (not scrollTop): works regardless of container nesting depth.
   */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, streaming?.text]);

  // Cleanup: abort any in-flight stream when the component unmounts
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // ── Handlers ───────────────────────────────────────────────────────────────

  /**
   * handleNewChat — creates a new conversation thread.
   *
   * WHY crypto.randomUUID() (not POST /v1/threads first):
   * We assign the thread_id client-side so streaming can begin immediately
   * without waiting for a round-trip. S9 creates the thread lazily on the
   * first POST /chat/stream if the thread_id doesn't exist yet.
   * This reduces perceived latency — the user can type immediately.
   */
  const handleNewChat = useCallback(() => {
    const newId = crypto.randomUUID();
    setActiveThreadId(newId);
    setLocalMessages([]);
    setStreaming(null);
    setChatError(null);
    setInput("");
    // Focus textarea so the user can type immediately
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, []);

  /**
   * handleSelectThread — load an existing thread.
   * Aborts any ongoing stream for the previous thread first.
   */
  const handleSelectThread = useCallback((threadId: string) => {
    // Cancel any in-flight stream for the previous thread
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setActiveThreadId(threadId);
    setStreaming(null);
    setChatError(null);
    setInput("");
  }, []);

  /**
   * handleDeleteThread — delete a thread and deselect it if active.
   */
  const handleDeleteThread = useCallback(
    async (threadId: string, e: React.MouseEvent) => {
      // WHY stopPropagation: clicking Delete inside the thread list item should
      // not also trigger the "select thread" click handler on the parent div.
      e.stopPropagation();
      try {
        await createGateway(accessToken).deleteThread(threadId);
        if (activeThreadId === threadId) {
          setActiveThreadId(null);
          setLocalMessages([]);
          setStreaming(null);
        }
        // Refetch thread list to reflect deletion
        void refetchThreads();
      } catch {
        // Silently fail — the thread may already be gone
      }
    },
    [accessToken, activeThreadId, refetchThreads],
  );

  /**
   * handleSend — POST to /v1/chat/stream and consume the SSE response.
   *
   * STATE MACHINE:
   *   idle → sending (user submits) → streaming (SSE data arrives) → idle ([DONE])
   *
   * ERROR PATHS:
   *   - Fetch fails (network error, S9 down): setChatError + reset to idle
   *   - Stream interrupted (reader done=true without [DONE]): show partial + note
   *   - 401/403: shows auth error (re-login needed)
   */
  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || streaming || !accessToken) return;

    // Auto-create a thread if none is selected
    let threadId = activeThreadId;
    if (!threadId) {
      threadId = crypto.randomUUID();
      setActiveThreadId(threadId);
    }

    // Optimistically add the user message to the local message list.
    // WHY optimistic: The user's question is certain — no need to wait for
    // S9 to echo it back. Creates a snappier feel.
    const userMessage: Message = {
      message_id: crypto.randomUUID(),
      thread_id: threadId,
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
      citations: [],
    };

    setLocalMessages((prev) => [...prev, userMessage]);
    setInput(""); // Clear input immediately — good UX, user can compose follow-up
    setChatError(null);

    // Create AbortController so the Cancel button can stop the stream
    const controller = new AbortController();
    abortRef.current = controller;

    // Show the typing indicator immediately
    setStreaming({ text: "", active: true });

    try {
      const response = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // WHY Authorization header (not URL param): tokens in URLs appear in
          // server logs, proxy logs, browser history. Bearer header is never logged.
          "Authorization": `Bearer ${accessToken}`,
        },
        // WHY `message` not `question`: S8 ChatRequestSchema expects `message` field.
        // (AI-005 fix: field name mismatch caused 422 validation error)
        body: JSON.stringify({ message: question, thread_id: threadId } satisfies {
          message: string;
          thread_id: string;
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Stream request failed: ${response.status} ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Response body is null — server did not return a stream");
      }

      const decoder = new TextDecoder();
      /**
       * WHY buffer: SSE chunks don't always align with newlines. A single
       * reader.read() call may return half a "data: ..." line or multiple lines.
       * The buffer accumulates bytes until we have a complete newline-terminated line.
       */
      let buffer = "";
      let finalContent = "";

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          // Stream ended without [DONE] sentinel — treat accumulated text as final
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        // Process all complete lines in the buffer
        const lines = buffer.split("\n");
        // Keep the last (possibly incomplete) line in the buffer for the next chunk
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue; // WHY: skip SSE comment/event-type lines

          const payload = line.slice(6); // strip "data: " prefix (6 chars)

          if (payload === "[DONE]") {
            // Stream complete — move accumulated text to the messages array
            setStreaming(null);
            if (finalContent) {
              const assistantMessage: Message = {
                message_id: crypto.randomUUID(),
                thread_id: threadId!,
                role: "assistant",
                content: finalContent,
                created_at: new Date().toISOString(),
                // WHY empty citations: Citations come from the thread history endpoint,
                // not the stream. After [DONE], a background refetch populates citations.
                citations: [],
              };
              setLocalMessages((prev) => [...prev, assistantMessage]);
            }
            // Refetch thread list to update the thread title (S9 sets it after first turn)
            void refetchThreads();
            return;
          }

          // Parse the JSON token payload
          try {
            const parsed = JSON.parse(payload) as { text?: string; token?: string };
            // WHY text ?? token: S8 SSE emitter sends {"text": ...} (AI-006 fix)
            const chunk = parsed.text ?? parsed.token;
            if (chunk) {
              finalContent += chunk;
              // WHY functional update: guarantees we always append to the latest state
              // even if React batches multiple setState calls before rendering.
              setStreaming((prev) =>
                prev ? { ...prev, text: prev.text + chunk } : prev,
              );
            }
          } catch {
            // Non-JSON line (keep-alive comment, empty line) — skip silently
          }
        }
      }

      // Stream ended (done=true) without [DONE] — show what we have
      setStreaming(null);
      if (finalContent) {
        const assistantMessage: Message = {
          message_id: crypto.randomUUID(),
          thread_id: threadId!,
          role: "assistant",
          content: finalContent + "\n\n[Response interrupted]",
          created_at: new Date().toISOString(),
          citations: [],
        };
        setLocalMessages((prev) => [...prev, assistantMessage]);
      }
    } catch (err) {
      // WHY check AbortError: when the user clicks Cancel, the fetch throws
      // an AbortError. That's expected — not a real error to display.
      if (err instanceof Error && err.name === "AbortError") {
        setStreaming(null);
        return;
      }
      setStreaming(null);
      setChatError(
        err instanceof Error ? err.message : "Chat request failed. Please try again.",
      );
    } finally {
      abortRef.current = null;
    }
  }, [input, streaming, accessToken, activeThreadId, refetchThreads]);

  /**
   * handleCancelStream — abort the current SSE stream.
   * WHY expose: LLM responses can be very long. Giving the user a Cancel button
   * respects their time — they can stop reading at any point without waiting.
   */
  const handleCancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStreaming(null);
  }, []);

  /**
   * handleKeyDown — Enter sends, Shift+Enter inserts newline.
   * WHY this pattern: Standard chat UX (Slack, Teams, Claude.ai).
   * Analysts frequently write multi-line questions ("Compare:\n- NVDA Q4\n- AMD Q4").
   */
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  // ── Derived state ──────────────────────────────────────────────────────────

  const isStreaming = streaming !== null;
  const isSendDisabled = !input.trim() || isStreaming || !accessToken;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    // WHY h-full overflow-hidden: The page sits inside the (app) layout's
    // <main className="flex-1 overflow-y-auto">. We want the chat to fill
    // that area without double-scrolling — the inner ScrollArea handles scroll.
    <div className="flex h-full overflow-hidden">

      {/* ════════════════════════════════════════════════════════════════════
          LEFT PANEL — Thread List (w-[280px])
          WHY fixed width (not flex): thread titles are variable length but
          the sidebar should never push the chat area below a usable width.
      ════════════════════════════════════════════════════════════════════ */}
      <aside
        className="flex w-[280px] shrink-0 flex-col border-r border-border bg-background"
        aria-label="Chat thread list"
      >
        {/* Header + New Chat button */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" />
            <span className="text-sm font-semibold text-foreground">Threads</span>
          </div>
          {/*
           * WHY "New chat" button: Prominent action that starts a fresh conversation.
           * Placed at the top — natural starting point for a new research session.
           */}
          <Button
            size="sm"
            variant="outline"
            onClick={handleNewChat}
            className="h-7 gap-1 border-primary/30 px-2 text-xs text-primary hover:bg-primary/10"
            aria-label="Start new chat"
          >
            <Plus className="h-3 w-3" />
            New chat
          </Button>
        </div>

        {/* Thread list body */}
        <ScrollArea className="flex-1">
          <div className="space-y-0.5 p-2">

            {/* Loading skeleton — shows while threads query is in-flight */}
            {threadsLoading && (
              <div className="space-y-1.5 p-1" aria-label="Loading threads">
                {[...Array(5)].map((_, i) => (
                  // WHY rounded-[2px] (was rounded-md): terminal 2px radius rule;
                  // WHY h-8 (was h-12): compact thread skeleton matching thread row height
                  <Skeleton key={i} className="h-8 w-full rounded-[2px]" />
                ))}
              </div>
            )}

            {/* Error state */}
            {threadsError && !threadsLoading && (
              <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                Failed to load threads. Check your connection.
              </div>
            )}

            {/* Empty state — first-time user or all threads deleted */}
            {/* WHY compact inline (was py-8 centered icon): terminal style */}
            {!threadsLoading && !threadsError && (!threads || threads.length === 0) && (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No conversations yet. Click &ldquo;New chat&rdquo; to begin.
              </p>
            )}

            {/* Thread items */}
            {threads?.map((thread) => {
              const isActive = thread.thread_id === activeThreadId;
              return (
                <div
                  key={thread.thread_id}
                  // WHY group: allows hover:visible on the delete button inside
                  // WHY rounded-[2px] (was rounded-md): terminal 2px radius rule
                  className="group relative flex cursor-pointer items-start gap-2 rounded-[2px] px-3 py-2.5 transition-colors hover:bg-muted"
                  // WHY bg-primary/10 on active: clear selection indicator using
                  // the Bloomberg Dark primary (#E8A317) at low opacity — not overwhelming.
                  // WHY inline style: Tailwind's dynamic class generation can't handle
                  // runtime conditionals in className for active thread highlighting.
                  // rgba(232,163,23,0.08) = Bloomberg Dark primary #E8A317 at 8% opacity.
                  style={isActive ? { backgroundColor: "rgba(232,163,23,0.08)" } : undefined}
                  onClick={() => handleSelectThread(thread.thread_id)}
                  role="button"
                  aria-pressed={isActive}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      handleSelectThread(thread.thread_id);
                    }
                  }}
                >
                  <div className="min-w-0 flex-1">
                    {/* Thread title — null until S9 sets it after first turn */}
                    <p
                      className={`truncate text-sm ${
                        isActive ? "font-medium text-primary" : "text-foreground"
                      }`}
                    >
                      {thread.title ?? PLACEHOLDER_THREAD_TITLE}
                    </p>
                    {/* WHY font-mono on date: dates are data, not prose */}
                    <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                      {new Date(thread.updated_at).toLocaleDateString([], {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>

                  {/*
                   * Delete button — hidden until hover (group-hover:flex).
                   * WHY hover-reveal (not always visible): avoids visual noise.
                   * The user needs to hover over the specific thread to see/click Delete.
                   */}
                  <button
                    className="hidden shrink-0 rounded-[2px] p-0.5 text-muted-foreground hover:text-destructive group-hover:flex"
                    onClick={(e) => void handleDeleteThread(thread.thread_id, e)}
                    aria-label={`Delete thread: ${thread.title ?? PLACEHOLDER_THREAD_TITLE}`}
                    tabIndex={-1} // WHY -1: delete is secondary action, not in tab order
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </aside>

      {/* ════════════════════════════════════════════════════════════════════
          RIGHT PANEL — Chat Area (flex-1)
      ════════════════════════════════════════════════════════════════════ */}
      <div className="flex flex-1 flex-col overflow-hidden">

        {/* ── No thread selected: welcome / empty state ── */}
        {/* WHY compact (was large centered icon + text-lg + p-8):
            Terminal chat empty states use compact inline messaging, not a marketing-style
            welcome card. The panel is part of a split layout — excessive padding
            creates a consumer-app feel. */}
        {!activeThreadId && (
          // WHY p-4 (was p-6): tighter padding for terminal panel welcome state
          <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-background p-4 text-center">
            <p className="text-sm font-semibold text-foreground">Intelligence Chat</p>
            <p className="max-w-sm text-xs text-muted-foreground">
              Ask research-grade questions about markets, companies, and news.
            </p>
            <Button
              size="sm"
              onClick={handleNewChat}
              className="mt-1 gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <Plus className="h-3.5 w-3.5" />
              Start a conversation
            </Button>
          </div>
        )}

        {/* ── Thread selected: message area + input ── */}
        {activeThreadId && (
          <>
            {/* Message list — scrollable, fills available height */}
            <ScrollArea className="flex-1 bg-background">
              {/* WHY p-4 gap-3 (was p-6 gap-4): tighter message spacing */}
              <div className="flex flex-col gap-3 p-4">

                {/* Loading skeleton while thread history is fetching */}
                {threadLoading && (
                  <div className="space-y-4" aria-label="Loading messages">
                    {[...Array(3)].map((_, i) => (
                      <Skeleton
                        key={i}
                        className={`h-16 w-2/3 rounded-[2px] ${
                          i % 2 === 0 ? "self-end" : "self-start"
                        }`}
                      />
                    ))}
                  </div>
                )}

                {/* ── Starter questions — shown when thread has no messages ────── */}
                {/* WHY 2-col grid: 6 questions fit in a balanced 3-row × 2-col layout
                    that fills the empty thread canvas without feeling sparse */}
                {!threadLoading && localMessages.length === 0 && !streaming && (
                  <div className="grid grid-cols-2 gap-2 p-3">
                    {STARTER_QUESTIONS.map((q, i) => {
                      // Replace [TICKER] placeholder with entity ticker from URL or leave as-is
                      const displayQuestion = q.replace(
                        "[TICKER]",
                        entityTicker ?? "[TICKER]",
                      );
                      return (
                        <button
                          key={i}
                          type="button"
                          // WHY rounded-[2px]: design system 2px radius everywhere
                          className={cn(
                            "rounded-[2px] border border-border bg-card",
                            "cursor-pointer p-3 text-left",
                            "hover:border-primary/40 hover:bg-muted/40",
                            "text-[12px] leading-relaxed text-foreground",
                            "transition-colors duration-0",
                          )}
                          // WHY inject into input (not send directly): trader may want
                          // to edit the question before sending — especially the
                          // [TICKER] placeholder variants.
                          onClick={() => setInput(displayQuestion)}
                        >
                          {displayQuestion}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Render persisted messages */}
                {localMessages.map((msg) => (
                  <MessageBubble key={msg.message_id} message={msg} />
                ))}

                {/* In-flight SSE stream */}
                {streaming && streaming.text ? (
                  // WHY only show StreamingBubble when there's text: avoids a flash
                  // of an empty bubble before the first token arrives.
                  <StreamingBubble streaming={streaming} />
                ) : streaming ? (
                  // Still waiting for first token — show animated typing indicator
                  <TypingIndicator />
                ) : null}

                {/* Error state — shown below the last message */}
                {chatError && (
                  <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                    {chatError}
                  </div>
                )}

                {/*
                 * WHY an empty div as scroll anchor:
                 * messagesEndRef.current.scrollIntoView() scrolls to this div,
                 * which is always the last element — keeps the latest message visible.
                 */}
                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {/* ── Input area ─────────────────────────────────────────────────── */}
            {/* WHY p-3 (was p-4): standard terminal panel padding */}
            <div className="border-t border-border bg-background p-3">
              {/* Entity context badge — shown when ?entity_id= param is set */}
              {/* WHY above input: the badge tells the trader which entity their
                  questions will be focused on. Placing it above the textarea
                  keeps it in natural reading order (context → input). */}
              {entityIdFromUrl && (
                <div className="mb-2 flex items-center gap-2 border-b border-border/40 pb-2">
                  <span className="rounded-[2px] bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary">
                    Context: {entityTicker ?? entityIdFromUrl}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    questions will focus on this entity
                  </span>
                </div>
              )}

              {/* Cancel button — only visible while streaming */}
              {isStreaming && (
                <div className="mb-2 flex justify-center">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleCancelStream}
                    className="h-7 border-destructive/30 px-3 text-xs text-destructive hover:bg-destructive/10"
                  >
                    Stop generating
                  </Button>
                </div>
              )}

              <div className="flex items-end gap-2">
                {/*
                 * WHY Textarea (not Input): Chat messages can be multi-line.
                 * Analysts write structured questions with bullet points.
                 * Auto-resize via row calculation keeps the box compact for short
                 * messages but grows for longer ones.
                 */}
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about markets, companies, news… (Enter to send, Shift+Enter for newline)"
                  rows={2}
                  disabled={isStreaming}
                  maxLength={2000} // WHY 2000: PRD-0028 §9.2 input validation limit
                  // WHY rounded-[2px] (was rounded-lg): terminal 2px radius rule
                  className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Chat message input"
                />

                <Button
                  onClick={() => void handleSend()}
                  disabled={isSendDisabled}
                  className="h-10 w-10 shrink-0 bg-primary p-0 text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>

              {/* Character count — visible when input is getting long */}
              {input.length > 1500 && (
                <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                  {input.length} / 2000
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
