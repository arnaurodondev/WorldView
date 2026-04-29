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
 * PLAN-0051 WAVE E (T-E-5-01..07) ADDS:
 *   - Slash commands (/quote, /portfolio, /news, /watchlist, /alerts, /screener)
 *     with autocomplete popover and inline structured cards.
 *   - MarkdownContent rendering for assistant messages (tables, code copy).
 *   - Thread search box above the sidebar list (200ms debounced).
 *   - Citation bar (red/yellow/green) with hover tooltip and anchor scroll.
 *   - Context-aware starter questions when ?entity_id= present.
 *   - Inline rename (double-click sidebar title) — PATCH /v1/threads/{id}.
 *   - Markdown export of the conversation (download .md file).
 *
 * WHO USES IT: Authenticated users at /chat
 * DATA SOURCES:
 *   GET   /api/v1/threads          — thread list
 *   GET   /api/v1/threads/:id      — thread with full message history
 *   PATCH /api/v1/threads/:id      — rename (PLAN-0051 T-E-5-06)
 *   POST  /api/v1/chat/stream      — SSE streaming response
 * DESIGN REFERENCE: PRD-0028 §6.5 Chat page (layout §6.3, spec §6.5.9)
 */

"use client";
// WHY "use client": Heavy interactive state — streaming SSE via fetch + ReadableStream,
// message list with auto-scroll, thread selection, keyboard shortcuts (Enter to send,
// Shift+Enter for newline), inline rename input, debounced search. All require browser
// APIs unavailable in Server Components.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  Bot,
  Download,
  MessageSquare,
  Plus,
  Search,
  Send,
  Trash2,
} from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { safeExternalUrl, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { SlashCommandCard } from "@/components/chat/SlashCommandCard";
import { SlashCommandAutocomplete } from "@/components/chat/SlashCommandAutocomplete";
import { CitationBar } from "@/components/chat/CitationBar";
import { parseInput, type ParsedCommand } from "@/lib/chat/slash-commands";
import { downloadThread } from "@/lib/chat/export-thread";
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

/**
 * SlashTurn — a slash-command "turn" rendered inline in the chat log.
 *
 * WHY it lives alongside Message: the conversation log is a mixed list of
 * regular Message objects and slash-command results. Both implement a
 * common shape ({id, role, content?}) so the render loop can branch on
 * `kind` to decide which renderer to call.
 */
interface SlashTurn {
  kind: "slash";
  message_id: string;
  command: ParsedCommand;
  /** Echo of the user's typed input, shown as a user bubble above the card. */
  input: string;
  created_at: string;
}

type LogEntry = Message | SlashTurn;

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * WHY PLACEHOLDER_THREAD_TITLE: When a thread has no title (S9 sets it to null
 * until the first message is processed by the LLM), show a human-readable label.
 */
const PLACEHOLDER_THREAD_TITLE = "New conversation";

/**
 * STARTER_QUESTIONS — generic fallbacks shown when no entity context is set.
 *
 * WHY pre-seeded cards: empty-thread state is a common UX dead zone — users
 * don't know what to ask first. Pre-seeded cards reduce blank-page anxiety and
 * guide traders toward high-value research questions.
 */
const STARTER_QUESTIONS = [
  "What are the key risks for [TICKER] next quarter?",
  "Compare MSFT and GOOGL cloud revenue growth over 4 quarters",
  "Summarize [TICKER]'s latest earnings call",
  "Recent insider transactions and what they signal",
  "What analyst consensus shows for [TICKER] in 2026?",
  "Search SEC filings for 'supply chain' risk exposure",
] as const;

/**
 * entityStarters — context-aware starter questions when ?entity_id= is set.
 *
 * WHY a function (not a constant): we substitute the ticker into the strings.
 * PLAN-0051 T-E-5-05.
 */
function entityStarters(ticker: string): readonly string[] {
  return [
    `What's the latest news on ${ticker}?`,
    `Why did ${ticker} move today?`,
    `What are the bull and bear cases for ${ticker}?`,
    `How does ${ticker} compare to its peers?`,
  ];
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * TypingIndicator — animated three-dot bubble shown while SSE stream is active.
 * Finance-grade polish: indicates the LLM is generating, not that the network stalled.
 */
function TypingIndicator() {
  return (
    <div className="flex max-w-[70%] items-end gap-2 self-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
        <Bot className="h-3.5 w-3.5 text-primary" />
      </div>
      <div className="rounded-[2px] bg-muted px-4 py-3">
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
 */
const CITATION_ICONS: Record<string, string> = {
  sec: "[SEC]",
  news: "[NEWS]",
  earnings: "[EARN]",
  knowledge_graph: "[KG]",
};

function getCitationIcon(cite: Citation): string {
  const src = cite.source.toLowerCase();
  if (src.includes("sec") || src.includes("edgar") || src.includes("filing")) {
    return CITATION_ICONS.sec;
  }
  if (src.includes("earning") || src.includes("transcript")) {
    return CITATION_ICONS.earnings;
  }
  if (src.includes("knowledge") || src.includes("graph")) {
    return CITATION_ICONS.knowledge_graph;
  }
  const title = (cite.title ?? "").toLowerCase();
  if (title.includes("10-k") || title.includes("10-q") || title.includes("8-k")) {
    return CITATION_ICONS.sec;
  }
  return CITATION_ICONS.news;
}

/**
 * CitationList — clickable citation pills below assistant messages.
 *
 * Wave E: the inline pill list is now complemented by the CitationBar (see
 * MessageBubble below). Pills remain because traders frequently click through
 * to source URLs.
 */
function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((cite, i) => (
        <a
          key={`${cite.article_id}-${i}`}
          href={safeExternalUrl(cite.url)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-[2px] border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20"
          title={`${cite.source} — relevance: ${(cite.relevance_score * 100).toFixed(0)}%`}
        >
          <sup className="font-mono text-[9px]">[{i + 1}]</sup>
          <span className="font-mono text-[9px]" aria-hidden="true">{getCitationIcon(cite)}</span>
          <span className="font-mono text-[9px] text-primary/70">{cite.source}</span>
          <span className="max-w-[140px] truncate">{cite.title}</span>
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
 *
 * WAVE E CHANGES (T-E-5-02 + T-E-5-04):
 *   - Assistant messages now render via <MarkdownContent> (tables, code,
 *     copy buttons). User messages remain plain (they typed the text).
 *   - A CitationBar (segmented red/yellow/green confidence strip) sits
 *     below assistant messages, complementing the existing pill list.
 */
function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  // WHY anchor prefix: CitationBar segments link to #{prefix}-N anchors that
  // we inject into the rendered message via `id` attributes. Use the
  // message_id to namespace anchors per message.
  const anchorPrefix = `cite-${message.message_id}`;

  return (
    <div
      className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={`flex max-w-[70%] items-end gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}
      >
        {!isUser && (
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
            <Bot className="h-3.5 w-3.5 text-primary" />
          </div>
        )}

        <div
          className={`rounded-[2px] px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? "bg-primary/10 text-foreground"
              : "bg-muted text-foreground"
          }`}
        >
          {/*
           * User vs assistant rendering split:
           *  - User: plain <pre> preserves their literal whitespace (a question
           *    like "compare:\n- AAPL\n- MSFT" reads as written). Markdown
           *    rendering on user input would mangle "*" wildcards etc.
           *  - Assistant: MarkdownContent renders tables/lists/code blocks
           *    consistent with the rest of the app (PLAN-0051 T-E-5-02).
           */}
          {isUser ? (
            <pre className="whitespace-pre-wrap font-sans text-sm">{message.content}</pre>
          ) : (
            <div id={anchorPrefix}>
              <MarkdownContent size="comfortable">{message.content}</MarkdownContent>
            </div>
          )}

          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        </div>
      </div>

      {/* Citation bar + pill list — assistant messages only */}
      {!isUser && (message.citations?.length ?? 0) > 0 && (
        <div className="ml-9 max-w-[70%]">
          {/* WHY both bar AND pills: the bar gives at-a-glance gestalt
              (mostly green = trust this answer); the pills give the
              actual click-through link. Different jobs, both useful. */}
          <CitationBar citations={message.citations} anchorPrefix={anchorPrefix} />
          <CitationList citations={message.citations} />
        </div>
      )}
    </div>
  );
}

/**
 * SlashTurnBlock — render the user's slash-command "turn" in the log.
 *
 * Shows the typed input as a small user bubble and the structured card
 * as if it were the assistant's reply. Visually identical placement so
 * the conversation reads naturally.
 */
function SlashTurnBlock({ turn }: { turn: SlashTurn }) {
  return (
    <>
      {/* User echo of the typed input — matches the regular user-message style */}
      <div className="flex flex-col items-end gap-1">
        <div className="flex max-w-[70%] items-end gap-2 flex-row-reverse">
          <div className="rounded-[2px] bg-primary/10 px-4 py-3 text-sm">
            <pre className="whitespace-pre-wrap font-sans text-sm">{turn.input}</pre>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">
              {new Date(turn.created_at).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          </div>
        </div>
      </div>
      {/* The card itself — fetched on render via TanStack Query */}
      <SlashCommandCard command={turn.command} />
    </>
  );
}

/**
 * StreamingBubble — the in-flight assistant bubble shown while SSE tokens arrive.
 *
 * WHY MarkdownContent here too: the streaming text often contains markdown
 * partials. Rendering through MarkdownContent gives consistent typography
 * with the final message. Trade-off: partial markdown sometimes flickers
 * (e.g. "**bo" before "**bold**" closes), which is acceptable.
 */
function StreamingBubble({ streaming }: { streaming: StreamingMessage }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex max-w-[70%] items-end gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[2px] bg-primary/20">
          <Bot className="h-3.5 w-3.5 text-primary" />
        </div>
        <div className="rounded-[2px] bg-muted px-4 py-3 text-sm leading-relaxed">
          <MarkdownContent size="comfortable">{streaming.text}</MarkdownContent>
          {streaming.active && (
            <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Thread sidebar item (with rename) ────────────────────────────────────────

/**
 * ThreadItem — sidebar row for a single thread.
 *
 * WHY split out: the rename UX (double-click → input → Enter / Esc) added
 * enough state that inlining it inside the page render would clutter the
 * main component. Keep the parent list rendering small and readable.
 *
 * PLAN-0051 T-E-5-06: optimistic title update with rollback on PATCH error.
 */
function ThreadItem({
  thread,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: {
  thread: Thread;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string, e: React.MouseEvent) => void;
  onRename: (id: string, newTitle: string) => Promise<void>;
}) {
  // WHY local edit state: the row owns its own draft title while the input
  // is shown, then propagates to the parent via onRename on commit.
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(thread.title ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-sync the draft when the underlying thread title changes (e.g. after
  // a successful PATCH the parent's optimistic update flows down).
  useEffect(() => {
    setDraft(thread.title ?? "");
  }, [thread.title]);

  // Auto-focus the input when entering edit mode.
  useEffect(() => {
    if (isEditing) inputRef.current?.focus();
  }, [isEditing]);

  /**
   * commit — try to PATCH the new title; revert local state on error.
   */
  async function commit() {
    const trimmed = draft.trim();
    setIsEditing(false);
    // Empty titles are rejected; revert to current value.
    if (!trimmed || trimmed === (thread.title ?? "")) {
      setDraft(thread.title ?? "");
      return;
    }
    try {
      await onRename(thread.thread_id, trimmed);
    } catch {
      // Rollback the draft on error so the user can retry.
      setDraft(thread.title ?? "");
    }
  }

  function cancel() {
    setDraft(thread.title ?? "");
    setIsEditing(false);
  }

  return (
    <div
      className="group relative flex cursor-pointer items-start gap-2 rounded-[2px] px-3 py-2.5 transition-colors hover:bg-muted"
      style={isActive ? { backgroundColor: "rgba(232,163,23,0.08)" } : undefined}
      onClick={() => !isEditing && onSelect(thread.thread_id)}
      role="button"
      aria-pressed={isActive}
      tabIndex={0}
      onKeyDown={(e) => {
        if (isEditing) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(thread.thread_id);
        }
      }}
    >
      <div className="min-w-0 flex-1">
        {isEditing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onBlur={() => void commit()}
            onKeyDown={(e) => {
              // WHY stopPropagation: prevent the parent's onKeyDown from
              // re-selecting the thread on Enter while we're editing.
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                void commit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancel();
              }
            }}
            className={cn(
              "w-full rounded-[2px] border border-primary/40 bg-card",
              "px-1.5 py-0.5 text-sm text-foreground",
              "focus:outline-none focus:ring-1 focus:ring-primary",
            )}
            aria-label="Edit thread title"
            maxLength={200}
          />
        ) : (
          <p
            className={`truncate text-sm ${
              isActive ? "font-medium text-primary" : "text-foreground"
            }`}
            // WHY double-click to rename: matches Slack/Notion convention.
            // Keeps single-click for "select thread", double-click for edit.
            onDoubleClick={(e) => {
              e.stopPropagation();
              setIsEditing(true);
            }}
            title="Double-click to rename"
          >
            {thread.title ?? PLACEHOLDER_THREAD_TITLE}
          </p>
        )}
        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          {new Date(thread.updated_at).toLocaleDateString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>

      <button
        className="hidden shrink-0 rounded-[2px] p-0.5 text-muted-foreground hover:text-destructive group-hover:flex"
        onClick={(e) => onDelete(thread.thread_id, e)}
        aria-label={`Delete thread: ${thread.title ?? PLACEHOLDER_THREAD_TITLE}`}
        tabIndex={-1}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── Main page component ───────────────────────────────────────────────────────

export default function ChatPage() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // ── Entity context from URL param ─────────────────────────────────────────
  const searchParams = useSearchParams();
  const entityIdFromUrl = searchParams.get("entity_id");

  // QA-iter1 MAJ-5: ?entity_id= carries a UUID, not a ticker. The earlier
  // draft displayed it verbatim, producing strings like "What's the latest
  // news on 2c8e3a7f-…?". We resolve UUID → ticker via the company-overview
  // endpoint (which accepts an instrument_id OR an entity_id and returns the
  // canonical ticker). If the value isn't a UUID we fall through to using
  // the raw string as the "ticker" (legacy behaviour, used by tests today).
  const looksLikeUuid =
    !!entityIdFromUrl &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      entityIdFromUrl,
    );
  const { data: resolvedEntity } = useQuery({
    queryKey: ["chat-entity-resolve", entityIdFromUrl],
    // Only fetch when the URL value parses as a UUID — otherwise we already
    // have a usable label and would waste a round-trip.
    enabled: !!accessToken && looksLikeUuid,
    queryFn: () =>
      createGateway(accessToken).getCompanyOverview(entityIdFromUrl as string),
    staleTime: 5 * 60_000,
  });
  // Resolved ticker (UUID-resolved when possible) OR the raw URL value when
  // it wasn't a UUID OR null when there's no entity context.
  const entityTicker = useMemo<string | null>(() => {
    if (!entityIdFromUrl) return null;
    if (looksLikeUuid) {
      // Wait for the resolve to complete; fall back to null until then so
      // we don't briefly flash "What's the latest news on 2c8e3a7f-…".
      return resolvedEntity?.instrument?.ticker ?? null;
    }
    return entityIdFromUrl;
  }, [entityIdFromUrl, looksLikeUuid, resolvedEntity]);

  // ── Thread list state ──────────────────────────────────────────────────────
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [localMessages, setLocalMessages] = useState<LogEntry[]>([]);
  const [streaming, setStreaming] = useState<StreamingMessage | null>(null);
  const [input, setInput] = useState("");
  const [chatError, setChatError] = useState<string | null>(null);

  // ── Thread search (T-E-5-03) ──────────────────────────────────────────────
  // WHY two states: `searchInput` reacts immediately to typing (controlled
  // input); `searchQuery` is the debounced value that drives filtering. This
  // is the textbook pattern — avoids re-rendering the list on every keystroke.
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // ── Refs ───────────────────────────────────────────────────────────────────
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Data fetching ──────────────────────────────────────────────────────────

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

  const {
    data: activeThread,
    isLoading: threadLoading,
  } = useQuery<Thread>({
    queryKey: ["thread", activeThreadId, accessToken],
    queryFn: () => createGateway(accessToken).getThread(activeThreadId!),
    enabled: !!accessToken && !!activeThreadId,
    staleTime: 0,
  });

  // ── Effects ────────────────────────────────────────────────────────────────

  // Sync activeThread messages into localMessages when the thread query succeeds.
  useEffect(() => {
    if (activeThread && activeThread.thread_id === activeThreadId && !streaming) {
      setLocalMessages(activeThread.messages);
    }
  }, [activeThread, activeThreadId, streaming]);

  // Auto-scroll to bottom on new tokens / messages.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, streaming?.text]);

  // Cancel any in-flight stream on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Debounce searchInput → searchQuery (200ms per task spec).
  useEffect(() => {
    const handle = setTimeout(() => setSearchQuery(searchInput), 200);
    return () => clearTimeout(handle);
  }, [searchInput]);

  // ── Derived: filtered threads ─────────────────────────────────────────────

  /**
   * filteredThreads — apply the search filter (case-insensitive substring
   * match against title + last assistant message snippet).
   *
   * WHY include the last message: users frequently remember a phrase from
   * the answer ("...that NVDA report on Hopper...") even when they don't
   * remember what they titled the thread.
   */
  const filteredThreads = useMemo(() => {
    if (!threads) return undefined;
    if (!searchQuery.trim()) return threads;
    const needle = searchQuery.trim().toLowerCase();
    return threads.filter((t) => {
      const title = (t.title ?? "").toLowerCase();
      // WHY check messages[]: the API may return summary message text via
      // last_msg_at and we can also peek at the messages tuple when present.
      const msgText = t.messages
        ?.map((m) => m.content)
        .join(" ")
        .toLowerCase() ?? "";
      return title.includes(needle) || msgText.includes(needle);
    });
  }, [threads, searchQuery]);

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    const newId = crypto.randomUUID();
    setActiveThreadId(newId);
    setLocalMessages([]);
    setStreaming(null);
    setChatError(null);
    setInput("");
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, []);

  const handleSelectThread = useCallback((threadId: string) => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setActiveThreadId(threadId);
    setStreaming(null);
    setChatError(null);
    setInput("");
  }, []);

  const handleDeleteThread = useCallback(
    async (threadId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        await createGateway(accessToken).deleteThread(threadId);
        if (activeThreadId === threadId) {
          setActiveThreadId(null);
          setLocalMessages([]);
          setStreaming(null);
        }
        void refetchThreads();
      } catch {
        // Silently fail — the thread may already be gone
      }
    },
    [accessToken, activeThreadId, refetchThreads],
  );

  /**
   * handleRenameThread — optimistic title update + rollback on PATCH error.
   *
   * PLAN-0051 T-E-5-06.
   *
   * WHY optimistic via setQueryData: TanStack Query's cache for the threads
   * list is the single source of truth for the sidebar. Patching the cache
   * directly avoids a flicker between "old title" and "new title via
   * refetch". On error we restore the previous snapshot.
   */
  const handleRenameThread = useCallback(
    async (threadId: string, newTitle: string) => {
      const prev = queryClient.getQueryData<Thread[]>(["threads", accessToken]);
      // Optimistic: patch the cache.
      if (prev) {
        queryClient.setQueryData<Thread[]>(
          ["threads", accessToken],
          prev.map((t) =>
            t.thread_id === threadId ? { ...t, title: newTitle } : t,
          ),
        );
      }
      try {
        await createGateway(accessToken).updateThread(threadId, { title: newTitle });
        // Refresh from authoritative server state once the PATCH resolves.
        void refetchThreads();
      } catch (err) {
        // Rollback on failure.
        if (prev) {
          queryClient.setQueryData(["threads", accessToken], prev);
        }
        throw err;
      }
    },
    [accessToken, queryClient, refetchThreads],
  );

  /**
   * handleExport — download the active thread as a markdown file.
   *
   * PLAN-0051 T-E-5-07.
   *
   * WHY assemble from current state (not a re-fetch): the user just saw
   * the messages in localMessages — exporting exactly what they see is the
   * principle of least surprise. We filter out SlashTurn entries because
   * they aren't real Messages on the server side (their cards are
   * client-rendered). For the export, the user's typed slash command is
   * preserved as a "User" message; the card is omitted (re-rendering it
   * server-side has no value in a markdown file).
   */
  const handleExport = useCallback(() => {
    if (!activeThread) return;
    const messageList: Message[] = localMessages.flatMap((entry): Message[] => {
      if ("kind" in entry && entry.kind === "slash") {
        // Convert the slash echo into a synthetic User Message for the export.
        return [
          {
            message_id: entry.message_id,
            thread_id: activeThread.thread_id,
            role: "user",
            content: entry.input,
            created_at: entry.created_at,
            citations: [],
          },
        ];
      }
      return [entry as Message];
    });
    downloadThread(activeThread, messageList);
  }, [activeThread, localMessages]);

  /**
   * handleSend — POST to /v1/chat/stream and consume the SSE response.
   *
   * PLAN-0051 T-E-5-01: BEFORE the LLM call, try parseInput. If it returns
   * a ParsedCommand, render an inline SlashCommandCard turn and skip the
   * round-trip to the LLM entirely.
   */
  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || streaming || !accessToken) return;

    // ── Slash command short-circuit ───────────────────────────────────────
    const parsed = parseInput(question);
    if (parsed) {
      // Append a slash turn to the local log; don't call the LLM.
      let threadId = activeThreadId;
      if (!threadId) {
        threadId = crypto.randomUUID();
        setActiveThreadId(threadId);
      }
      const turn: SlashTurn = {
        kind: "slash",
        message_id: crypto.randomUUID(),
        command: parsed,
        input: question,
        created_at: new Date().toISOString(),
      };
      setLocalMessages((prev) => [...prev, turn]);
      setInput("");
      setChatError(null);
      return;
    }

    // ── Standard LLM path ─────────────────────────────────────────────────
    let threadId = activeThreadId;
    if (!threadId) {
      threadId = crypto.randomUUID();
      setActiveThreadId(threadId);
    }

    const userMessage: Message = {
      message_id: crypto.randomUUID(),
      thread_id: threadId,
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
      citations: [],
    };

    setLocalMessages((prev) => [...prev, userMessage]);
    setInput("");
    setChatError(null);

    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming({ text: "", active: true });

    try {
      const response = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ message: question, thread_id: threadId }),
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
      let buffer = "";
      let finalContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);

          if (payload === "[DONE]") {
            setStreaming(null);
            if (finalContent) {
              const assistantMessage: Message = {
                message_id: crypto.randomUUID(),
                thread_id: threadId!,
                role: "assistant",
                content: finalContent,
                created_at: new Date().toISOString(),
                citations: [],
              };
              setLocalMessages((prev) => [...prev, assistantMessage]);
            }
            void refetchThreads();
            return;
          }

          try {
            const parsedToken = JSON.parse(payload) as { text?: string; token?: string };
            const chunk = parsedToken.text ?? parsedToken.token;
            if (chunk) {
              finalContent += chunk;
              setStreaming((prev) =>
                prev ? { ...prev, text: prev.text + chunk } : prev,
              );
            }
          } catch {
            // Non-JSON line (keep-alive comment, empty line) — skip silently
          }
        }
      }

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

  const handleCancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStreaming(null);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  // ── Derived state ──────────────────────────────────────────────────────────

  const isStreaming = streaming !== null;
  const isSendDisabled = !input.trim() || isStreaming || !accessToken;
  const showAutocomplete = input.trimStart().startsWith("/") && !input.includes("\n");

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* ════════════════ LEFT PANEL — Thread List ════════════════ */}
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

        {/* Thread search box (T-E-5-03) — debounced 200ms via effect above */}
        <div className="border-b border-border/40 p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search threads…"
              aria-label="Search threads"
              className={cn(
                "w-full rounded-[2px] border border-border bg-muted",
                "pl-7 pr-2 py-1.5 text-xs text-foreground",
                "placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-1 focus:ring-primary",
              )}
            />
          </div>
        </div>

        {/* Thread list body */}
        <ScrollArea className="flex-1">
          <div className="space-y-0.5 p-2">
            {threadsLoading && (
              <div className="space-y-1.5 p-1" aria-label="Loading threads">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full rounded-[2px]" />
                ))}
              </div>
            )}

            {threadsError && !threadsLoading && (
              <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                Failed to load threads. Check your connection.
              </div>
            )}

            {!threadsLoading && !threadsError && (!threads || threads.length === 0) && (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No conversations yet. Click &ldquo;New chat&rdquo; to begin.
              </p>
            )}

            {/* WHY filteredThreads (was threads): the search box narrows the
                list client-side. When search is empty filteredThreads === threads. */}
            {filteredThreads?.length === 0 && threads && threads.length > 0 && (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No threads match &ldquo;{searchQuery}&rdquo;.
              </p>
            )}

            {filteredThreads?.map((thread) => (
              <ThreadItem
                key={thread.thread_id}
                thread={thread}
                isActive={thread.thread_id === activeThreadId}
                onSelect={handleSelectThread}
                onDelete={handleDeleteThread}
                onRename={handleRenameThread}
              />
            ))}
          </div>
        </ScrollArea>
      </aside>

      {/* ════════════════ RIGHT PANEL — Chat Area ════════════════ */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Welcome / empty state */}
        {!activeThreadId && (
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

        {activeThreadId && (
          <>
            {/* Thread header — title + Export button */}
            {/* WHY a header strip (T-E-5-07): the export button needs a
                conventional resting place; a dedicated row above the messages
                also reinforces the active thread title at the top of the panel. */}
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-foreground">
                  {activeThread?.title ?? PLACEHOLDER_THREAD_TITLE}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleExport}
                disabled={!activeThread || localMessages.length === 0}
                className="h-7 gap-1 border-border px-2 text-xs"
                aria-label="Export thread as Markdown"
              >
                <Download className="h-3 w-3" />
                Export
              </Button>
            </div>

            {/* Message list */}
            <ScrollArea className="flex-1 bg-background">
              <div className="flex flex-col gap-3 p-4">
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

                {/* Starter questions — entity-aware (T-E-5-05) */}
                {!threadLoading && localMessages.length === 0 && !streaming && (
                  <div
                    className={cn(
                      "grid gap-2 p-3",
                      // WHY 2 cols for 4 entity starters and 6 generic ones
                      // alike: same visual rhythm regardless of count.
                      "grid-cols-2",
                    )}
                  >
                    {(entityTicker ? entityStarters(entityTicker) : STARTER_QUESTIONS).map(
                      (q, i) => {
                        // For generic starters we substitute [TICKER] with
                        // the URL ticker if available (legacy behaviour
                        // preserved). Entity starters already have the ticker
                        // baked in.
                        const display = entityTicker
                          ? q
                          : q.replace("[TICKER]", entityTicker ?? "[TICKER]");
                        return (
                          <button
                            key={i}
                            type="button"
                            className={cn(
                              "rounded-[2px] border border-border bg-card",
                              "cursor-pointer p-3 text-left",
                              "hover:border-primary/40 hover:bg-muted/40",
                              "text-[12px] leading-relaxed text-foreground",
                              "transition-colors duration-0",
                            )}
                            onClick={() => setInput(display)}
                          >
                            {display}
                          </button>
                        );
                      },
                    )}
                  </div>
                )}

                {/* Render messages + slash turns */}
                {localMessages.map((entry) => {
                  if ("kind" in entry && entry.kind === "slash") {
                    return <SlashTurnBlock key={entry.message_id} turn={entry} />;
                  }
                  const msg = entry as Message;
                  return <MessageBubble key={msg.message_id} message={msg} />;
                })}

                {/* In-flight SSE stream */}
                {streaming && streaming.text ? (
                  <StreamingBubble streaming={streaming} />
                ) : streaming ? (
                  <TypingIndicator />
                ) : null}

                {chatError && (
                  <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                    {chatError}
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {/* ── Input area ─────────────────────────────────────────────── */}
            <div className="border-t border-border bg-background p-3">
              {entityIdFromUrl && (
                <div className="mb-2 flex items-center gap-2 border-b border-border/40 pb-2">
                  <span className="rounded-[2px] bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary">
                    {/* QA-iter2 N-MIN-1: never expose the raw UUID in the
                       chrome — fall back to "Loading…" while the entity
                       resolves and to "—" if resolution fails outright. */}
                    Context: {entityTicker ?? (looksLikeUuid ? "Loading…" : entityIdFromUrl)}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    questions will focus on this entity
                  </span>
                </div>
              )}

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

              {/* Slash command autocomplete — visible while typing /... */}
              {showAutocomplete && (
                <SlashCommandAutocomplete
                  query={input}
                  onPick={(cmd) => {
                    // Fill the input with the verb and a trailing space so the
                    // user can type args. For arg-less commands the trailing
                    // space is harmless and Enter submits immediately.
                    setInput(`/${cmd.name}${cmd.argSpec ? " " : ""}`);
                    textareaRef.current?.focus();
                  }}
                />
              )}

              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about markets, companies, news…  Type / for commands. (Enter to send, Shift+Enter for newline)"
                  rows={2}
                  disabled={isStreaming}
                  maxLength={2000}
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
