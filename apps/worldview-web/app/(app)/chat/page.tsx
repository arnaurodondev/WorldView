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
import { useRouter, useSearchParams } from "next/navigation";
import {
  Download,
  MessageSquare,
  Plus,
  Search,
  Send,
} from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// WHY qk: removes inline queryKey arrays and the accessToken-in-key anti-pattern.
// Including accessToken in a queryKey causes cache thrashing when the token
// rotates (OIDC refresh every ~30min) — old cache entries are orphaned and
// every rotation fires an unnecessary refetch. Auth is enforced by `enabled:
// !!accessToken`; the token itself need not be part of the cache identity.
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SlashCommandAutocomplete } from "@/components/chat/SlashCommandAutocomplete";
import { downloadThread } from "@/lib/chat/export-thread";
import type { Thread, Message } from "@/types/api";

// ── PLAN-0059 E-3 partial — extracted sub-components + types + helpers ───────
// The chat page held 7 inline render components + 2 type aliases + a starter-
// questions helper (~430 LOC of the original 1,332). They now live under
// `features/chat/`. The streamChat / abort / SSE handling stays in this
// page — extracting it would require another careful pass and is the
// remaining E-3 work tracked as E-3-followup.
import {
  TypingIndicator,
  MessageBubble,
  StreamingBubble,
} from "@/features/chat/components/MessageBubble";
import { SlashTurnBlock } from "@/features/chat/components/SlashTurnBlock";
import { ThreadItem } from "@/features/chat/components/ThreadItem";
import {
  PLACEHOLDER_THREAD_TITLE,
  STARTER_QUESTIONS,
  PORTFOLIO_STARTER_QUESTIONS,
  entityStarters,
} from "@/features/chat/lib/starters";
import { MarketContextBanner } from "@/components/chat/MarketContextBanner";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
// PLAN-0082 Wave B: write-action confirmation modal.
// WHY imported here (not at component file boundary): the modal needs
// `accessToken` from the page's `useAuth()` call and the `pendingAction` /
// `clearPendingAction` values from `useChatStream`. Both live at this page
// level, so the modal is wired here rather than inside a sub-component.
import { ActionConfirmModal } from "@/features/chat/components/ActionConfirmModal";

// ── Main page component ───────────────────────────────────────────────────────

export default function ChatPage() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // ── Entity context from URL param ─────────────────────────────────────────
  const searchParams = useSearchParams();
  // PLAN-0052 platform-QA round 5: router for the 401 re-auth CTA below.
  const router = useRouter();
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
    // WHY qk.chat.entityResolve: avoids the old inline ["chat-entity-resolve", id]
    // literal. Lives under the chat.* namespace so a chat-wide invalidation
    // (e.g. on logout) clears this cache entry too.
    queryKey: qk.chat.entityResolve(entityIdFromUrl ?? ""),
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
  const [input, setInput] = useState("");

  // ── Thread search (T-E-5-03) ──────────────────────────────────────────────
  // WHY two states: `searchInput` reacts immediately to typing (controlled
  // input); `searchQuery` is the debounced value that drives filtering. This
  // is the textbook pattern — avoids re-rendering the list on every keystroke.
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // ── Refs ───────────────────────────────────────────────────────────────────
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // PLAN-0053 T-F-6-05: preserve thread sidebar scroll across refetches.
  // Without this, every threads refetch rebuilds the list DOM and the
  // sidebar springs back to the top — disorienting when the user has
  // scrolled to find an older thread. We capture scrollTop just before
  // the refetch invalidation and restore it once the new list is mounted.
  const sidebarScrollRef = useRef<HTMLDivElement>(null);
  const savedScrollTopRef = useRef<number>(0);

  // ── Data fetching ──────────────────────────────────────────────────────────

  const {
    data: threads,
    isLoading: threadsLoading,
    error: threadsError,
    refetch: refetchThreads,
  } = useQuery<Thread[]>({
    // WHY qk.chat.threads() (was ["threads", accessToken]):
    // accessToken in the key caused cache thrashing on every 30-min OIDC
    // token rotation — the old entry became orphaned and a new fetch fired
    // even though the user's identity hadn't changed. Auth is enforced by
    // `enabled: !!accessToken`; the token itself need not be part of the
    // cache identity. See PLAN-0070 D-1 T-D-1-03.
    queryKey: qk.chat.threads(),
    queryFn: () => createGateway(accessToken).getThreads(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  const {
    data: activeThread,
    isLoading: threadLoading,
  } = useQuery<Thread>({
    // WHY qk.chat.thread(id) (was ["thread", id, accessToken]):
    // Same accessToken-in-key anti-pattern as above. Also: staleTime was 0,
    // which forced a full refetch every time the chat panel re-rendered
    // (e.g. on streaming state transitions). 30s staleTime means TanStack
    // Query returns the cached thread instantly while the background refetch
    // runs — preventing the "blank message list on re-mount" flash.
    queryKey: qk.chat.thread(activeThreadId ?? ""),
    queryFn: () => createGateway(accessToken).getThread(activeThreadId!),
    enabled: !!accessToken && !!activeThreadId,
    staleTime: 30_000,
  });

  // ── SSE chat stream ───────────────────────────────────────────────────────
  // PLAN-0059 E-3 follow-up: the entire send/stream/abort lifecycle moved to
  // `useChatStream`. The page just wires the inputs (auth token, active
  // thread id, refetcher) and reads the resulting view state.
  const {
    localMessages,
    setLocalMessages,
    streaming,
    chatError,
    isStreaming,
    // PLAN-0067 W11-5: activeTools drives the ToolCallIndicator inside StreamingBubble.
    // Populated by tool_call SSE events, cleared on done/cancel.
    activeTools,
    // PLAN-0082 Wave B: pending write-action confirmation (create_alert, etc.).
    // pendingAction is non-null when the backend emits a ``pending_action`` SSE event.
    // clearPendingAction is passed to ActionConfirmModal as `onDismiss`.
    pendingAction,
    clearPendingAction,
    send,
    cancel: handleCancelStream,
    resetForThread,
  } = useChatStream({
    accessToken,
    activeThreadId,
    setActiveThreadId,
    refetchThreads: () => {
      void refetchThreads();
    },
  });

  // ── Effects ────────────────────────────────────────────────────────────────

  // Sync activeThread messages into localMessages when the thread query succeeds.
  // STAYS AT PAGE LEVEL: this depends on TanStack Query data (`activeThread`)
  // which is owned by the page. The hook only manages transient streaming
  // state — historical messages come from the server cache.
  useEffect(() => {
    if (activeThread && activeThread.thread_id === activeThreadId && !streaming) {
      setLocalMessages(activeThread.messages);
    }
  }, [activeThread, activeThreadId, streaming, setLocalMessages]);

  // Auto-scroll to bottom on new tokens / messages.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, streaming?.text]);

  // Debounce searchInput → searchQuery (200ms per task spec).
  useEffect(() => {
    const handle = setTimeout(() => setSearchQuery(searchInput), 200);
    return () => clearTimeout(handle);
  }, [searchInput]);

  // PLAN-0053 T-F-6-05: capture+restore sidebar scroll across thread refetches.
  //
  // STRATEGY: the actual scroll container is the Radix ScrollArea Viewport,
  // not the content div the ref points at. We walk up the tree to find the
  // closest element with `data-radix-scroll-area-viewport`. Capturing scroll
  // events on a ref (cheap, no re-render) preserves performance for long
  // lists; restoring after every refetch keeps the user's position stable.
  //
  // WHY a ref + native scroll listener: updating React state on every scroll
  // event would re-render the entire sidebar and tank performance for long
  // thread lists. The ref pattern is the canonical fix.
  useEffect(() => {
    const inner = sidebarScrollRef.current;
    if (!inner) return;
    const viewport = inner.closest<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (!viewport) return;
    const handleScroll = () => {
      savedScrollTopRef.current = viewport.scrollTop;
    };
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  // Restore scrollTop after every refetch (when `threads` identity changes).
  useEffect(() => {
    const inner = sidebarScrollRef.current;
    if (!inner) return;
    const viewport = inner.closest<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (!viewport) return;
    if (savedScrollTopRef.current > 0) {
      viewport.scrollTop = savedScrollTopRef.current;
    }
  }, [threads]);

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
    // resetForThread aborts in-flight stream + clears messages/error in the hook.
    resetForThread();
    setInput("");
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [resetForThread]);

  const handleSelectThread = useCallback(
    (threadId: string) => {
      // resetForThread aborts the active stream so its tokens don't bleed
      // into the newly-selected thread's log.
      resetForThread();
      setActiveThreadId(threadId);
      setInput("");
    },
    [resetForThread],
  );

  const handleDeleteThread = useCallback(
    async (threadId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        await createGateway(accessToken).deleteThread(threadId);
        if (activeThreadId === threadId) {
          setActiveThreadId(null);
          // Hook owns the messages + streaming bubble for the active thread.
          resetForThread();
        }
        void refetchThreads();
      } catch {
        // Silently fail — the thread may already be gone
      }
    },
    [accessToken, activeThreadId, refetchThreads, resetForThread],
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
      const prev = queryClient.getQueryData<Thread[]>(qk.chat.threads());
      // Optimistic: patch the cache.
      if (prev) {
        queryClient.setQueryData<Thread[]>(
          qk.chat.threads(),
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
          queryClient.setQueryData(qk.chat.threads(), prev);
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
   * handleSend — page-side wrapper around `useChatStream.send`.
   *
   * The hook owns the slash-command branch + LLM SSE flow. Here we only
   * pull the current input, clear it (UX expectation: the textarea empties
   * the moment the user hits Enter), then delegate.
   */
  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question) return;
    setInput("");
    await send(question);
  }, [input, send]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  // ── P2C-3: Entity Quick-Chips — derived from current thread messages ─────
  //
  // WHY extract from message content: the thread data has no structured
  // `context_entities` field today. We scan user messages for capitalized
  // 1–5 char strings (standard ticker format) as a lightweight proxy.
  // This gives the analyst one-click pivoting to instruments already
  // mentioned in the thread without retyping. Bloomberg Terminal convention:
  // entity chips appear above the command line for entities in context.
  //
  // WHY user messages only (not assistant): assistant messages contain tickers
  // too, but also many false positives (e.g. "The SEC filed an 8-K about GHJ"
  // where "SEC" and "GHJ" are not investable tickers). User messages are where
  // the analyst explicitly named the instruments they care about.
  //
  // WHY max 5: limited chip rail space in the 320px input footer. 5 chips
  // fit comfortably without wrapping to a second row or crowding the textarea.
  const activeEntityChips = useMemo<string[]>(() => {
    if (!activeThreadId || localMessages.length === 0) return [];

    const TICKER_RE = /\b([A-Z]{1,5})\b/g;
    // Common English words that match the pattern but aren't tickers.
    const SKIP = new Set([
      "I", "A", "AN", "THE", "AND", "OR", "NOT", "FOR", "OF", "IN",
      "ON", "AT", "TO", "BY", "BE", "DO", "IF", "UP", "NO", "VS",
      "AI", "US", "UK", "EU", "Q", "S", "W", "E", "N", "M",
    ]);

    const seen = new Set<string>();
    for (const entry of localMessages) {
      // Only scan user messages — assistant messages have too many false positives.
      if ("kind" in entry) continue; // slash turn
      const msg = entry as { role: string; content: string };
      if (msg.role !== "user") continue;
      let m: RegExpExecArray | null;
      const re = new RegExp(TICKER_RE.source, "g");
      while ((m = re.exec(msg.content)) !== null) {
        const tok = m[1];
        if (!SKIP.has(tok) && tok.length >= 2) {
          seen.add(tok);
        }
      }
    }

    // Also surface the entity from the URL param if resolved.
    if (entityTicker) seen.add(entityTicker);

    return [...seen].slice(0, 5);
  }, [activeThreadId, localMessages, entityTicker]);

  /**
   * appendToInput — append a string to the current textarea value.
   *
   * WHY a named helper (not inline onClick): the same append logic is
   * needed both by entity chips and potentially by other future chip types
   * (e.g. /news slash command shortcut). Naming it makes tests cleaner.
   *
   * WHY trim then re-add space: avoids double-spaces when the input already
   * ends with a space, but also avoids gluing the appended text to the last
   * word (e.g. "about AAPL$MSFT" instead of "about AAPL $MSFT").
   */
  const appendToInput = useCallback((suffix: string) => {
    setInput((prev) => {
      const trimmed = prev.trimEnd();
      return trimmed ? `${trimmed}${suffix}` : suffix.trimStart();
    });
    // Re-focus the textarea so the user can keep typing immediately after
    // clicking a chip — avoids a two-step click-then-click-textarea flow.
    setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  // ── Derived state ──────────────────────────────────────────────────────────

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
        {/* PLAN-0071 P2C-1: market session status strip — grounds the
            intelligence panel in real market context so analysts know
            at a glance whether they're in live-session or planning mode. */}
        <MarketContextBanner />

        {/* Header + New Chat button */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" strokeWidth={1.5} />
            <span className="text-sm font-semibold text-foreground">Threads</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={handleNewChat}
            className="h-7 gap-1 border-primary/30 px-2 text-xs text-primary hover:bg-primary/10"
            aria-label="Start new chat"
          >
            <Plus className="h-3 w-3" strokeWidth={1.5} />
            New chat
          </Button>
        </div>

        {/* Thread search box (T-E-5-03) — debounced 200ms via effect above */}
        <div className="border-b border-border/40 p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" strokeWidth={1.5} />
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
        {/* PLAN-0053 T-F-6-05: ref attached to the inner content div. The
            useEffect below walks up to the Radix ScrollArea Viewport (which
            is the actual scroll container) by reading the
            `[data-radix-scroll-area-viewport]` attribute on the parent. Direct
            ref on the content gives a stable handle without forking
            scroll-area.tsx. */}
        <ScrollArea className="flex-1">
          <div ref={sidebarScrollRef} className="space-y-0.5 p-2">
            {threadsLoading && (
              <div className="space-y-1.5 p-1" aria-label="Loading threads">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full rounded-[2px]" />
                ))}
              </div>
            )}

            {threadsError && !threadsLoading && (
              // PLAN-0052 platform-QA round 5 (2026-05-01): better thread-list
              // error UX. The previous banner just said "Failed to load
              // threads, check your connection" which was misleading the most
              // common cause was a 401 from a lapsed JWT (no auto-refresh).
              // Detect 401 specifically and surface a Re-authenticate CTA;
              // for everything else fall back to the generic message + Retry.
              <div className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                {(() => {
                  const msg = (threadsError as Error)?.message ?? "";
                  const is401 =
                    msg.includes("401") ||
                    msg.toLowerCase().includes("unauthor");
                  return is401 ? (
                    <>
                      <p className="font-medium">Your session expired.</p>
                      <p className="mt-1">
                        Sign in again to load your conversations.
                      </p>
                      <button
                        type="button"
                        onClick={() => router.push("/login?redirect_to=/chat")}
                        className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20"
                      >
                        Sign in
                      </button>
                    </>
                  ) : (
                    <>
                      <p>Failed to load threads. Check your connection.</p>
                      <button
                        type="button"
                        onClick={() => void refetchThreads()}
                        className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20"
                      >
                        Retry
                      </button>
                    </>
                  );
                })()}
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

      {/* ════════════════ PLAN-0082 Wave B — Action Confirm Modal ════════════ */}
      {/* WHY outside the right panel div: Radix Dialog uses a Portal to render
          the overlay + content at the document body level. Placing this inside
          the layout div would still work (Portal escapes the DOM hierarchy), but
          keeping it as a sibling to the panels makes the render tree clearer —
          the modal is not a child of either panel; it floats above both. */}
      <ActionConfirmModal
        pendingAction={pendingAction}
        accessToken={accessToken}
        onDismiss={clearPendingAction}
      />

      {/* ════════════════ RIGHT PANEL — Chat Area ════════════════ */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Welcome / empty state — PLAN-0071 P2C-4: analyst-specific copy
            replaces the generic chatbot welcome. The two-line hierarchy
            (label + description) mirrors Bloomberg COMMAND BAR prompt
            style — short imperative, then scope clarification. */}
        {!activeThreadId && (
          // WHY p-3 (was p-4): the empty-state welcome is rendered inside an
          // already-bounded panel; 12px padding keeps the welcome text close
          // to the surrounding panel chrome instead of floating in 16px ports.
          <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-background p-3 text-center">
            <div className="space-y-1">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.10em] text-muted-foreground">
                Analyst Intelligence
              </p>
              <p className="max-w-[280px] text-[11px] leading-relaxed text-muted-foreground">
                Research-grade Q&A on earnings, SEC filings, macro, and your
                portfolio — grounded in real source documents, not hallucination.
              </p>
            </div>

            {/* PLAN-0071 P2C-2: portfolio-scoped starter questions shown in
                the no-thread-selected panel. Analysts landing here have no
                active entity context — portfolio-level questions surface the
                most immediately useful research directions. */}
            <div className="mt-1 grid w-full max-w-[440px] grid-cols-2 gap-1.5">
              {PORTFOLIO_STARTER_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    // Pre-fill the input state first — the textarea is not
                    // mounted yet (activeThreadId is null), but setInput just
                    // sets React state. When handleNewChat() sets activeThreadId
                    // and the input area mounts, it will read the already-set value.
                    setInput(q);
                    handleNewChat();
                  }}
                  className="rounded-[2px] border border-border bg-card p-2.5 text-left text-[10px] leading-relaxed text-foreground hover:border-primary/40 hover:bg-muted/40 transition-colors duration-0"
                >
                  {q}
                </button>
              ))}
            </div>

            <Button
              size="sm"
              onClick={handleNewChat}
              className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
              New conversation
            </Button>
          </div>
        )}

        {activeThreadId && (
          <>
            {/* Thread header — title + Export button.
                WHY a header strip (T-E-5-07): the export button needs a
                conventional resting place; a dedicated row above the messages
                also reinforces the active thread title at the top of the panel.
                WHY px-3 (was px-4 py-2): matches the TopBar/sub-header
                12-px horizontal rhythm — pass-2 polish defect 1G. */}
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
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
                <Download className="h-3 w-3" strokeWidth={1.5} />
                Export
              </Button>
            </div>

            {/* Message list */}
            <ScrollArea className="flex-1 bg-background">
              <div className="flex flex-col gap-3 p-3">
                {/* WHY p-3 (was p-4): terminal-density reading area; matches
                    the post-F3 chat empty-state padding. Pass-2 defect 1G. */}
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
                              "text-[11px] leading-relaxed text-foreground",
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
                  // Pass activeTools so ToolCallIndicator renders above the streaming text.
                  // WHY: during multi-tool responses the tool indicators appear first,
                  // then text flows in below them once S8 starts generating.
                  <StreamingBubble streaming={streaming} activeTools={activeTools} />
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

              {/* P2C-3: Entity quick-chips — visible in active threads that
                  have at least one user message mentioning a ticker.
                  WHY entity chips: quick-pivot to related instruments. Clicking
                  a chip appends "$TICKER" to the input so analysts can ask
                  follow-up questions about mentioned entities without retyping.
                  Bloomberg Terminal convention: quick-select chips for entities
                  in context appear above the command line. */}
              {activeEntityChips.length > 0 && !showAutocomplete && (
                <div className="mb-2 flex flex-wrap items-center gap-1">
                  {/* WHY "Related:" label: makes the chip rail self-explanatory
                      to analysts who haven't seen it before. Without a label the
                      row of mono chips could be mistaken for keyboard shortcuts. */}
                  <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/60">
                    Related:
                  </span>
                  {activeEntityChips.map((ticker) => (
                    <button
                      key={ticker}
                      type="button"
                      onClick={() => appendToInput(` $${ticker}`)}
                      title={`Add ${ticker} to query`}
                      // WHY rounded-[2px]: terminal 2px radius rule.
                      // WHY tabular-nums: ticker characters are numbers/letters at
                      // a uniform width — tabular-nums prevents layout shift when
                      // the chip content changes (e.g. on thread switch).
                      className="rounded-[2px] border border-border/70 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-foreground transition-colors hover:border-primary/50 hover:text-primary"
                    >
                      {ticker}
                    </button>
                  ))}
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
                  className="flex-1 resize-none rounded-[2px] border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
                  aria-label="Chat message input"
                />

                <Button
                  onClick={() => void handleSend()}
                  disabled={isSendDisabled}
                  className="h-10 w-10 shrink-0 bg-primary p-0 text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" strokeWidth={1.5} />
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
