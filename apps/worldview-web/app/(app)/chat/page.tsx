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
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCcw,
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
// Round 3 Polish: shared empty-state primitive (DS §15.12) for the
// no-history sidebar + the empty-conversation welcome. Copy lives in
// lib/copy/empty-states.ts under the chat.* keys.
import { EmptyState } from "@/components/primitives/EmptyState";
// Round 3 Polish: canonical focus-ring class strings (PRD-0089 F1 §3.2) —
// Tier-2 input ring for the search box + composer textarea.
import { FocusRing } from "@/components/primitives/FocusRing";
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
  MessageBubble,
  StreamingBubble,
} from "@/features/chat/components/MessageBubble";
import { SlashTurnBlock } from "@/features/chat/components/SlashTurnBlock";
import { ThreadItem } from "@/features/chat/components/ThreadItem";
import {
  PLACEHOLDER_THREAD_TITLE,
  STARTER_QUESTIONS,
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
// PLAN-0099 W4: right-side context rail — entity card, citations, contradictions,
// related tickers. Collapsed by Cmd+\ keyboard shortcut (wired below).
import { ChatContextRail } from "@/features/chat/components/ChatContextRail";
// Round 1 Foundation: date-bucketed sidebar groups (Today / Yesterday / …).
import { groupThreadsByDate } from "@/features/chat/lib/group-threads";
// Round 2 Enhancement: suggested follow-up chips under the latest completed
// assistant answer. FollowUpChips is the (pre-existing, Wave-K) pure
// presenter; generateFollowUps is the new deterministic client-side
// generator (S8's SSE stream emits no suggestions event today — verified in
// useChatStream's demux — so the client synthesises them from the turn's
// detected tickers, citation titles, and tool usage).
import { FollowUpChips } from "@/features/chat/components/FollowUpChips";
// Round 3 Polish: welcomeStarterPrompts draws the empty-conversation welcome
// chips from the SAME generic pool generateFollowUps pads with, so pre-first-
// message suggestions and post-answer suggestions speak one language.
import {
  generateFollowUps,
  welcomeStarterPrompts,
} from "@/features/chat/lib/follow-ups";
// Round 2 Enhancement: shared conversation ticker extractor — the same
// detection the ChatContextRail uses, so the chips' entity substitutions
// always agree with the cards the analyst sees in the rail.
import { extractTickers } from "@/features/chat/lib/ticker-extract";
// Round 1 Foundation (PRD-0089 Q-8): debug-only tool trace drawer. The
// useDebugFlag gate means the drawer code path is completely inert (no
// listeners, no render) unless ?debug=1 is in the URL.
import { ToolTraceDrawer } from "@/features/chat/components/ToolTraceDrawer";
import { useDebugFlag } from "@/features/chat/hooks/useDebugFlag";
import { useToolTraceChord } from "@/features/chat/hooks/useToolTraceChord";

// ── Main page component ───────────────────────────────────────────────────────

export default function ChatPage() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // ── Entity context from URL param ─────────────────────────────────────────
  const searchParams = useSearchParams();
  // PLAN-0052 platform-QA round 5: router for the 401 re-auth CTA below.
  const router = useRouter();
  const entityIdFromUrl = searchParams.get("entity_id");
  // Round 2 Enhancement: ?thread=<id> deep-link support. The command palette
  // (Round 1) navigates to /chat?thread=<id> when the user picks a recent
  // conversation — until now the param was silently ignored and the page
  // landed on the empty state. Consumed by the effect below (after the
  // useChatStream hook is initialised, because applying the param must abort
  // any in-flight stream via resetForThread).
  const threadIdFromUrl = searchParams.get("thread");

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

  // ── Context rail collapse state ───────────────────────────────────────────
  // WHY default false (open): the rail is the primary added value of this
  // layout. Analysts who don't want it can collapse with Cmd+\. Starting
  // collapsed would hide the feature entirely on first load.
  const [isContextRailCollapsed, setIsContextRailCollapsed] = useState(false);

  // ── Thread list state ──────────────────────────────────────────────────────
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");

  // Round 1 Foundation: collapsible history sidebar. Default OPEN — history
  // is core navigation; collapsing is an opt-in to maximise the message
  // column on small screens. When collapsed we render a slim 36px rail with
  // just the expand affordance (full unmount would lose the user's mental
  // anchor of "the history lives on the left").
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Round 1 Foundation (PRD-0089 Q-8): ?debug=1 gate + ⌘D chord for the
  // ToolTraceDrawer. With debug off the chord hook registers nothing.
  const isDebug = useDebugFlag();
  const { isOpen: isTraceOpen, close: closeTrace } = useToolTraceChord(isDebug);

  // PLAN-0103 W3: ephemeral thread ids — client-minted UUIDs that don't yet
  // exist on the backend. When the user clicks "New chat" we mint a UUID for
  // SSE correlation, but firing getThread(id) before any message has been sent
  // produces a 404 + chat error banner. Track these ids here so the per-thread
  // useQuery can be disabled until the first send promotes the id to a real
  // server-side row (cleared when the threads list refetch sees it).
  const [ephemeralThreadIds, setEphemeralThreadIds] = useState<Set<string>>(
    () => new Set(),
  );
  const isEphemeralActive =
    !!activeThreadId && ephemeralThreadIds.has(activeThreadId);

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
    // PLAN-0103 W3: hold the fetch back for ephemeral (client-minted) ids —
    // see ephemeralThreadIds above. The id is only "real" once the threads
    // list refetch sees it (or the first SSE round-trip completes).
    enabled: !!accessToken && !!activeThreadId && !isEphemeralActive,
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
    // PLAN-0099 W4: latest agent_iteration event — drives the always-visible
    // AgentIterationProgress strip inside the StreamingBubble. Eliminates the
    // perceived hang between tool batches on multi-iteration research queries.
    iterationEvent,
    // Round 1 Foundation: per-turn debug tool trace (args/result/latency)
    // for the ?debug=1 ToolTraceDrawer below.
    toolTrace,
    send,
    // Round 1 Foundation: resubmits the last failed question without
    // duplicating its user bubble — wired to the error banner's Retry button.
    retry,
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

  // Round 2 Enhancement: consume the ?thread=<id> URL param.
  //
  // WHY a "last applied" ref (not a one-shot mount flag): the command palette
  // can fire /chat?thread=B while the user is ALREADY on /chat?thread=A — the
  // page doesn't remount, only searchParams changes, so the effect must
  // re-apply for every NEW param value. But it must apply each value exactly
  // ONCE: after the user manually selects a different thread in the sidebar,
  // the stale ?thread= param is still in the URL, and re-applying it on the
  // next render would yank the user back to the deep-linked thread (a
  // fight-the-user loop). The ref records which param value was already
  // honoured so subsequent renders leave the user's manual selection alone.
  const appliedThreadParamRef = useRef<string | null>(null);
  useEffect(() => {
    if (!threadIdFromUrl) return;
    if (appliedThreadParamRef.current === threadIdFromUrl) return;
    appliedThreadParamRef.current = threadIdFromUrl;
    // No-op when the deep-linked thread is already active (e.g. the user
    // refreshed the page and React re-ran the effect after hydration).
    if (threadIdFromUrl === activeThreadId) return;
    // Same sequence as handleSelectThread: abort any in-flight stream first
    // so its tokens can't bleed into the deep-linked thread's log, then
    // activate. The per-thread useQuery (keyed on activeThreadId) fetches the
    // full message history automatically once the id is set.
    resetForThread();
    setActiveThreadId(threadIdFromUrl);
  }, [threadIdFromUrl, activeThreadId, resetForThread]);

  // Sync activeThread messages into localMessages when the thread query succeeds.
  // STAYS AT PAGE LEVEL: this depends on TanStack Query data (`activeThread`)
  // which is owned by the page. The hook only manages transient streaming
  // state — historical messages come from the server cache.
  // FR-5.1 (HIGH-010): removed `&& !streaming` guard.
  // The original guard prevented history from syncing when a stream just
  // completed — exactly when the authoritative server messages should land.
  // The ref-based `isStreamingRef` in `useChatStream` already blocks concurrent
  // `send()` calls; this effect only replaces the optimistic log with the
  // settled server state, which is always safe to do.
  useEffect(() => {
    if (activeThread && activeThread.thread_id === activeThreadId) {
      setLocalMessages(activeThread.messages);
    }
  }, [activeThread, activeThreadId, setLocalMessages]);

  // PLAN-0103 W3: promote ephemeral ids once the threads list refresh sees
  // them. After this clears, the per-thread useQuery becomes enabled and the
  // historical messages back-fill normally.
  useEffect(() => {
    if (!threads || ephemeralThreadIds.size === 0) return;
    const known = new Set(threads.map((t) => t.thread_id));
    let changed = false;
    const next = new Set(ephemeralThreadIds);
    for (const id of ephemeralThreadIds) {
      if (known.has(id)) {
        next.delete(id);
        changed = true;
      }
    }
    if (changed) setEphemeralThreadIds(next);
  }, [threads, ephemeralThreadIds]);

  // Auto-scroll to bottom on new tokens / messages.
  //
  // Round 3 transition polish: behaviour is INSTANT ("auto") while a stream
  // is in flight and SMOOTH only for settled-message changes. WHY: smooth
  // scrolling is an ~300ms animated glide — SSE tokens arrive every ~20-50ms,
  // so each new token kicked off a fresh glide before the previous one
  // finished. The animations fought each other, producing a rubber-banding
  // viewport that lagged behind the text. Instant keeps the cursor pinned
  // frame-perfect during streams; the smooth glide remains for the rarer,
  // discrete events (user bubble appended, thread history loaded).
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: streaming ? "auto" : "smooth",
    });
  }, [localMessages, streaming?.text, streaming]);

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

  // ── Cmd+\ context rail toggle ─────────────────────────────────────────────
  //
  // WHY document-level listener (not a button's onKeyDown):
  // Cmd+\ is a global shortcut — it fires regardless of which element has
  // keyboard focus. document.addEventListener is the correct mechanism.
  // WHY cleanup in return: prevents the listener from accumulating if this
  // component re-mounts (e.g. hot-reload in dev).
  // WHY no animation: design spec mandates no transitions; the rail snaps to
  // 0 width or full width instantly.
  useEffect(() => {
    function handleContextRailToggle(e: KeyboardEvent) {
      // Cmd+\ on macOS (metaKey + Backslash) or Ctrl+\ on Windows/Linux.
      if ((e.metaKey || e.ctrlKey) && e.key === "\\") {
        e.preventDefault();
        setIsContextRailCollapsed((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleContextRailToggle);
    return () => document.removeEventListener("keydown", handleContextRailToggle);
  }, []);

  // ── Round 1 Foundation: restore composer focus when a stream ends ─────────
  //
  // WHY: the textarea is disabled while streaming (prevents double-send).
  // Disabling a focused element BLURS it, so after every answer the analyst
  // had to click back into the input before typing the follow-up — a
  // terminal-grade chat must keep the keyboard flow unbroken. When
  // isStreaming transitions true→false we re-focus the textarea.
  //
  // WHY track the previous value in a ref: focusing on EVERY render where
  // isStreaming === false would steal focus from the search box / rename
  // input every time anything re-renders. We only act on the transition.
  const wasStreamingRef = useRef(false);
  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      // requestAnimationFrame: the textarea re-enables in the SAME commit
      // that flips isStreaming — focusing immediately can race the disabled
      // attribute removal in some browsers. One frame later is always safe.
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
    wasStreamingRef.current = isStreaming;
  }, [isStreaming]);

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

  /**
   * groupedThreads — date buckets (Today / Yesterday / Previous 7 days /
   * Older) over the SEARCH-FILTERED list, so searching narrows within the
   * same grouped layout instead of switching to a different flat view.
   * Round 1 Foundation — chat history sidebar.
   */
  const groupedThreads = useMemo(
    () => (filteredThreads ? groupThreadsByDate(filteredThreads) : undefined),
    [filteredThreads],
  );

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleNewChat = useCallback(() => {
    const newId = crypto.randomUUID();
    // PLAN-0103 W3: mark as ephemeral so the per-thread useQuery stays
    // disabled until the backend acknowledges the id (first SSE completion
    // promotes it via the threads list refetch).
    setEphemeralThreadIds((prev) => {
      const next = new Set(prev);
      next.add(newId);
      return next;
    });
    setActiveThreadId(newId);
    // resetForThread aborts in-flight stream + clears messages/error in the hook.
    resetForThread();
    setInput("");
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, [resetForThread]);

  // ── Round 3: welcome-state starter prompts ────────────────────────────────
  //
  // Drawn from the follow-ups generator's GENERIC pool (welcomeStarterPrompts)
  // so the "what can I ask?" chips an analyst sees before their first message
  // use the exact same phrasing as the post-answer follow-up chips — one
  // suggestion vocabulary across the whole surface. Deterministic slice (no
  // hash), so the welcome never reshuffles between visits.
  const welcomeStarters = useMemo(() => welcomeStarterPrompts(4), []);

  /**
   * handlePickWelcomeStarter — welcome chip click → new thread + pre-filled
   * composer.
   *
   * ORDER MATTERS (Round 3 bug fix): the previous welcome cards called
   * `setInput(prompt)` BEFORE `handleNewChat()` — but handleNewChat ends with
   * `setInput("")`, so React applied prompt-then-empty in the same commit and
   * the composer always came up BLANK. Calling handleNewChat first makes the
   * clear happen before the pre-fill, so the prompt survives.
   */
  const handlePickWelcomeStarter = useCallback(
    (prompt: string) => {
      handleNewChat();
      setInput(prompt);
    },
    [handleNewChat],
  );

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
    // Round 1 Foundation: ⌘+Enter / Ctrl+Enter is an EXPLICIT submit chord —
    // the power-user convention shared with code editors and Slack. Checked
    // FIRST (before the plain-Enter branch) so the modifier path is
    // guaranteed even if the plain-Enter behaviour ever changes.
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void handleSend();
      return;
    }
    // Plain Enter submits; Shift+Enter inserts a newline (legacy behaviour,
    // documented in the placeholder text).
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

  // ── Round 2: suggested follow-up chips ────────────────────────────────────
  //
  // Shown under the LATEST assistant answer only, and only while the
  // conversation is at rest. The "disappear once the next message is sent"
  // requirement falls out of the derivation for free: the moment the user
  // sends anything, the optimistic user bubble becomes the last log entry,
  // the `last.role === "assistant"` guard fails, and the chips vanish — no
  // separate dismissed-state bookkeeping to leak across threads.
  //
  // WHY client-side generation: S8's SSE stream has no suggestions event
  // (verified against useChatStream's demux: token/citations/tool_call/
  // tool_result/agent_iteration/pending_action/error/done). When the backend
  // grows one, prefer it and keep generateFollowUps as the fallback.
  const followUpSuggestions = useMemo<string[]>(() => {
    // At-rest guards: never show "what next?" chips while an answer is still
    // streaming (they'd suggest follow-ups to an answer the user can't read
    // yet) or under an error banner (Retry is the only sensible next action).
    if (isStreaming || chatError) return [];
    const last = localMessages[localMessages.length - 1];
    // Slash turns ("kind" in entry) render structured cards, not prose —
    // template follow-ups make no sense under a /quote table.
    if (!last || "kind" in last || last.role !== "assistant" || !last.content) {
      return [];
    }
    return generateFollowUps({
      answerText: last.content,
      // Same extractor (and therefore the same blocklist + recency order) as
      // the context rail, so chip entities always match the rail's cards.
      tickers: extractTickers(
        localMessages.filter((e) => !("kind" in e)) as Message[],
      ).tickers,
      citationTitles: (last.citations ?? []).map((c) => c.title),
      // toolTrace survives stream completion precisely so post-hoc consumers
      // like this one can see WHICH tools produced the settled answer.
      toolsUsed: toolTrace.map((t) => t.tool),
    });
  }, [localMessages, isStreaming, chatError, toolTrace]);

  /**
   * handlePickFollowUp — chip click submits the suggestion as the next user
   * message immediately (TradingView/Perplexity pattern: click = send, no
   * intermediate "fill the composer and wait" step — the chip text is
   * already a complete question).
   */
  const handlePickFollowUp = useCallback(
    (suggestion: string) => {
      void send(suggestion);
    },
    [send],
  );

  // ── Derived state ──────────────────────────────────────────────────────────

  const isSendDisabled = !input.trim() || isStreaming || !accessToken;
  const showAutocomplete = input.trimStart().startsWith("/") && !input.includes("\n");

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* ════════════════ LEFT PANEL — Thread List ════════════════ */}
      {/* Density bundle 2026-05-09: w-[280px] → w-[224px] (= w-56). The 280px
          sidebar was inherited from a consumer-chatbot layout (Slack/Claude)
          but on a terminal the message column is the high-density surface and
          deserves the extra 56px of horizontal real estate. 224px still fits
          the "New chat" button + search box + 11px thread title without
          truncating the dev seed titles. */}
      {/* Round 1 Foundation: collapsed variant — a slim 36px rail keeping the
          expand affordance (and a quick New-chat) visible. WHY render a rail
          instead of unmounting: zero-width removal makes the history feel
          "gone" and the only way back would be a floating button over the
          messages — the rail preserves the spatial anchor. */}
      {/* Round 3 transition polish: ONE <aside> whose WIDTH animates between
          the expanded 224px panel and the slim 36px rail (150ms ease-out per
          the sprint spec — the only sanctioned structural transition on this
          surface; motion-reduce disables it). The previous implementation
          swapped two separate <aside> elements, which snapped instantly and
          yanked the message column sideways. The inner content still swaps
          per-state (the slim rail shows only icons), but the container width
          interpolates so the layout reflow reads as a deliberate slide.
          overflow-hidden clips the expanded content during the shrink. */}
      <aside
        className={cn(
          "flex shrink-0 flex-col overflow-hidden border-r border-border bg-background",
          "transition-[width] duration-150 ease-out motion-reduce:transition-none",
          isSidebarCollapsed ? "w-9" : "w-[224px]",
        )}
        aria-label={
          isSidebarCollapsed ? "Chat thread list (collapsed)" : "Chat thread list"
        }
      >
      {isSidebarCollapsed ? (
        <div className="flex flex-col items-center gap-1 py-2">
          <button
            type="button"
            onClick={() => setIsSidebarCollapsed(false)}
            aria-label="Expand thread list"
            // Round 3 focus polish: chrome icon buttons get a keyboard ring.
            className="rounded-[2px] p-1 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
          >
            <PanelLeftOpen className="h-4 w-4" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={handleNewChat}
            aria-label="Start new chat"
            title="New chat"
            className="rounded-[2px] p-1 text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
          >
            <Plus className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>
      ) : (
      <>
        {/* PLAN-0071 P2C-1: market session status strip — grounds the
            intelligence panel in real market context so analysts know
            at a glance whether they're in live-session or planning mode. */}
        <MarketContextBanner />

        {/* Header + New Chat button */}
        {/* Density bundle 2026-05-09: px-4 py-3 → px-3 py-2; text-sm → text-[11px]
            uppercase tracking-wide so the "Threads" label matches the rest of
            the platform's terminal section labels (e.g. WatchlistPanel, Alerts). */}
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <div className="flex items-center gap-1.5">
            {/* Round 1 Foundation: collapse toggle lives where the user's eye
                already rests (panel header) — same pattern as IDE side panels. */}
            <button
              type="button"
              onClick={() => setIsSidebarCollapsed(true)}
              aria-label="Collapse thread list"
              // Round 3 focus polish: keyboard ring on the chrome button.
              className="rounded-[2px] p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
            >
              <PanelLeftClose className="h-3.5 w-3.5" strokeWidth={1.5} />
            </button>
            <MessageSquare className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
            {/* Round 3 typography: panel heading aligned to the app-wide
                widget-header pattern (10px sans uppercase tracking-[0.08em]
                muted — cf. dashboard widgets + the context rail's "Context"
                header) so the two chat side panels share one heading scale. */}
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Threads
            </span>
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
                // Round 3 focus polish: canonical Tier-2 input ring (adds the
                // :focus-visible variant the inline classes were missing).
                "focus:outline-none",
                FocusRing.T2_INPUT,
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
              // Round 3 skeleton polish: each placeholder mirrors the real
              // ThreadItem anatomy (11px title line + 10px mono timestamp
              // line, px-2 py-1.5 row padding) instead of a featureless h-8
              // block — the list "develops" in place rather than morphing
              // from grey slabs into two-line rows. Title widths alternate
              // so the column doesn't look like a barcode.
              <div className="space-y-0.5" aria-label="Loading threads">
                {[...Array(5)].map((_, i) => (
                  <div
                    key={i}
                    data-testid="thread-skeleton-row"
                    className="space-y-1 rounded-[2px] px-2 py-1.5"
                  >
                    <Skeleton
                      className={cn(
                        "h-3 rounded-[2px]",
                        i % 2 === 0 ? "w-3/4" : "w-1/2",
                      )}
                    />
                    <Skeleton className="h-2.5 w-2/5 rounded-[2px]" />
                  </div>
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
                        // Round 3 focus polish: destructive-context ring (a
                        // primary/amber ring inside a red banner would clash).
                        className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-destructive"
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
                        // Round 3 focus polish: destructive-context ring.
                        className="mt-2 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-destructive"
                      >
                        Retry
                      </button>
                    </>
                  );
                })()}
              </div>
            )}

            {/* Round 3 empty-state migration: the bare <p> becomes the shared
                EmptyState primitive (DS §15.12) so the no-history sidebar
                renders identically to every other cold-start surface. Copy
                key chat.no-threads keeps the "No conversations yet" title the
                existing test pins. condition=empty-cold-start: the user has
                an account but hasn't produced data yet (FU-10.11 taxonomy). */}
            {!threadsLoading && !threadsError && (!threads || threads.length === 0) && (
              <EmptyState
                condition="empty-cold-start"
                copyKey="chat.no-threads"
                icon={MessageSquare}
              />
            )}

            {/* WHY filteredThreads (was threads): the search box narrows the
                list client-side. When search is empty filteredThreads === threads. */}
            {filteredThreads?.length === 0 && threads && threads.length > 0 && (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No threads match &ldquo;{searchQuery}&rdquo;.
              </p>
            )}

            {/* Round 1 Foundation: date-bucketed history. Each group renders a
                sticky-feeling section header (Today / Yesterday / …) above its
                rows. Empty groups are omitted by groupThreadsByDate, so a new
                user with 2 threads sees at most 2 headers — no scaffolding. */}
            {groupedThreads?.map((group) => (
              <div key={group.label}>
                <p
                  // Round 3 typography: date-bucket headers join the app-wide
                  // widget-header pattern (sans, tracking-[0.08em]) — they are
                  // category labels, not numeric data, so ADR-F-15's mono rule
                  // doesn't apply. 9px is sanctioned for list-section labels
                  // (§15.9 metadata exception); /70 keeps them sub-ordinate to
                  // the 10px "Threads" panel heading above.
                  className="px-2 pb-0.5 pt-2 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/70"
                  // WHY role=heading: lets screen-reader users jump between
                  // date buckets the same way sighted users scan the headers.
                  role="heading"
                  aria-level={3}
                >
                  {group.label}
                </p>
                {group.threads.map((thread) => (
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
            ))}
          </div>
        </ScrollArea>
      </>
      )}
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

      {/* ════════════════ CENTRE + RIGHT — Chat Area + Context Rail ════════════ */}
      {/*
       * WHY this wrapper div: we need the message column and the context rail
       * to sit side-by-side inside the outer flex. The message column is
       * flex-1 (grows to fill remaining space); the rail is w-[320px] shrink-0.
       * Without this wrapper div, ActionConfirmModal would separate them in
       * the outer flex row. The wrapper is purely structural — no visual effect.
       *
       * WHY overflow-hidden on wrapper: the rail and message column each have
       * their own overflow-y-auto / ScrollArea. The wrapper must NOT scroll
       * itself (overflow-hidden prevents a double-scrollbar).
       */}
      <div className="flex flex-1 overflow-hidden">
      {/* ════════════════ RIGHT PANEL — Chat Area ════════════════ */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Welcome / empty-conversation state — Round 3 polish.
            Migrated onto the shared EmptyState primitive (DS §15.12): icon
            category signal (MessageSquare), one-line value prop from the
            chat.welcome copy key, then a single action slot stacking the
            starter chips + the New-conversation CTA. WHY the primitive now
            (Wave K's ChatEmptyState deliberately skipped it): the Round-2
            icon/action API additions cover exactly what the welcome needs,
            so a hand-rolled layout is no longer justified.
            The 6-card portfolio starter grid is replaced by 3-4 chips drawn
            from the follow-ups generator's generic pool (sprint spec §4) —
            the richer entity/portfolio starter cards still appear INSIDE a
            new empty thread (STARTER_QUESTIONS grid below), so discovery is
            deferred one click, not lost. */}
        {!activeThreadId && (
          <div className="flex flex-1 flex-col items-center justify-center bg-background p-3">
            <EmptyState
              condition="empty-cold-start"
              copyKey="chat.welcome"
              icon={MessageSquare}
              action={
                <div className="mt-1 flex max-w-[440px] flex-col items-center gap-3">
                  {/* Reusing the FollowUpChips presenter keeps welcome chips
                      pixel-identical to post-answer follow-up chips (same
                      mono 10px chrome, hover, focus ring). ariaLabel swaps
                      so screen readers announce "Starter prompts", not
                      follow-ups to a nonexistent answer. */}
                  <FollowUpChips
                    suggestions={welcomeStarters}
                    onPick={handlePickWelcomeStarter}
                    ariaLabel="Starter prompts"
                  />
                  <Button
                    size="sm"
                    onClick={handleNewChat}
                    className="gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
                  >
                    <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
                    New conversation
                  </Button>
                </div>
              }
            />
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
            <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
              {/* Density bundle 2026-05-09: text-sm (14px) → text-[12px] for the
                  thread title; py-2 → py-1.5 to match TopBar rhythm. The thread
                  title is a header label, not data — 12px keeps it readable
                  while pulling it closer to the surrounding 11px text scale. */}
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12px] font-semibold text-foreground">
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
            {/* Density bundle 2026-05-09: gap-3 → gap-2 between messages.
                Tighter inter-message gap reduces wasted vertical real estate
                without losing message-boundary clarity (each bubble has its
                own bg + rounded corners). */}
            <ScrollArea className="flex-1 bg-background">
              <div className="flex flex-col gap-2 p-3">
                {/* WHY p-3 (was p-4): terminal-density reading area; matches
                    the post-F3 chat empty-state padding. Pass-2 defect 1G. */}
                {threadLoading && (
                  // Round 3 skeleton polish: bubble-SHAPED placeholders for
                  // the thread-switch loading window. Two fixes over the old
                  // version: (1) the wrapper was `space-y-4` (block layout),
                  // so the `self-end`/`self-start` alternation NEVER applied
                  // — flex-col makes the user/assistant alternation real;
                  // (2) assistant-side rows now carry the 28px avatar square
                  // so the silhouette matches MessageBubble exactly and the
                  // real conversation materialises without a layout pop.
                  <div
                    className="flex flex-col gap-3"
                    aria-label="Loading messages"
                  >
                    {[...Array(3)].map((_, i) =>
                      i % 2 === 0 ? (
                        // Even rows: user bubble silhouette (right-aligned).
                        <Skeleton
                          key={i}
                          data-testid="message-skeleton-user"
                          className="h-12 w-1/2 self-end rounded-[2px]"
                        />
                      ) : (
                        // Odd rows: assistant silhouette — avatar square +
                        // wider bubble, left-aligned like MessageBubble.
                        <div
                          key={i}
                          data-testid="message-skeleton-assistant"
                          className="flex items-end gap-2 self-start"
                        >
                          <Skeleton className="h-7 w-7 shrink-0 rounded-[2px]" />
                          <Skeleton className="h-16 w-[260px] rounded-[2px]" />
                        </div>
                      ),
                    )}
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
                              // Round 3 hover/focus polish: hover bg-muted
                              // (sprint-canonical) + keyboard focus ring.
                              "hover:border-primary/40 hover:bg-muted",
                              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary",
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

                {/* Round 2: suggested follow-ups under the latest settled
                    assistant answer. followUpSuggestions is [] while
                    streaming / on error / when the last entry isn't an
                    assistant message, so this renders nothing in all those
                    states (FollowUpChips additionally requires >=2 chips).
                    WHY pl-9: indents the chips to align with the assistant
                    bubble text (28px avatar + 8px gap), reading as "options
                    attached to this answer" rather than a free-floating row. */}
                {/* Round 3 transition polish: min-h matches the spacer
                    reserved below the StreamingBubble while the answer is in
                    flight — when the stream settles, the chips slot replaces
                    the spacer 1:1 so the column's bottom edge doesn't move
                    (no layout jump, no scroll fight). */}
                {followUpSuggestions.length > 0 && (
                  <div className="min-h-[26px] pl-9">
                    <FollowUpChips
                      suggestions={followUpSuggestions}
                      onPick={handlePickFollowUp}
                    />
                  </div>
                )}

                {/* In-flight SSE stream */}
                {/* FR-5.5 (MED-012): always render StreamingBubble when streaming is
                    non-null. StreamingBubble already handles the "no text yet" case
                    internally via ToolCallIndicator (shows tool spinners while
                    streaming.text === ""). The TypingIndicator fallback was redundant
                    and caused a brief flash between tool events and text arrival. */}
                {streaming ? (
                  // Pass activeTools so ToolCallIndicator renders above the streaming text.
                  // WHY: during multi-tool responses the tool indicators appear first,
                  // then text flows in below them once S8 starts generating.
                  <StreamingBubble
                    streaming={streaming}
                    activeTools={activeTools}
                    /*
                     * PLAN-0099 W4: pass the latest agent_iteration event so the
                     * always-visible progress strip stays alive through the silent
                     * gaps between tool batches (planning → reasoning → synthesis).
                     * Null until the first event arrives, then non-null until the
                     * stream completes — the strip handles its own visibility.
                     */
                    iterationEvent={iterationEvent}
                  />
                ) : null}

                {/* Round 3 transition polish: reserve the follow-up chips'
                    row height (26px ≈ chip 22px + mt-1) while the answer is
                    streaming. When the stream settles, the StreamingBubble is
                    replaced by the final MessageBubble AND the chips render —
                    in the SAME commit (the chips memo derives synchronously
                    from localMessages). With this spacer the chips occupy
                    already-reserved space instead of growing the column,
                    so the settled answer doesn't "jump" down a line. */}
                {streaming ? (
                  <div className="min-h-[26px]" aria-hidden="true" />
                ) : null}

                {chatError && (
                  // Round 1 Foundation: failed sends now surface a Retry CTA.
                  // WHY role=alert: error text must be announced by screen
                  // readers the moment it appears, not on next focus.
                  <div
                    role="alert"
                    className="rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive"
                  >
                    <p>{chatError}</p>
                    <button
                      type="button"
                      // retry() resends the last failed question WITHOUT
                      // duplicating its user bubble (skipUserEcho inside the
                      // hook) and clears this banner eagerly so the user sees
                      // the new attempt start immediately.
                      onClick={() => void retry()}
                      // Round 3 focus polish: keyboard-visible ring on the
                      // Retry CTA — destructive-context ring colour so the
                      // focus visual stays inside the banner's palette.
                      className="mt-2 inline-flex items-center gap-1 rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-destructive"
                    >
                      <RotateCcw className="h-3 w-3" strokeWidth={1.5} />
                      Retry
                    </button>
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
                      // Round 3 focus polish: keyboard ring matching the
                      // context rail's ticker chips (same chip species).
                      className="rounded-[2px] border border-border/70 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-foreground transition-colors hover:border-primary/50 hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
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
                  // Round 3 input polish: lead with WHAT to ask (the sprint's
                  // canonical helpful prompt), keep the / discovery hint, and
                  // drop the Enter/Shift+Enter legend — key behaviour is
                  // muscle-memory by now and the legend made the placeholder
                  // a wall of text. While streaming, the placeholder explains
                  // WHY the input is disabled instead of going silent —
                  // "visually clear but not jarring": the user reads intent,
                  // not just greyed-out chrome.
                  placeholder={
                    isStreaming
                      ? "Generating — use Stop to interrupt…"
                      : "Ask about any company, sector, or your portfolio…  Type / for commands."
                  }
                  rows={2}
                  disabled={isStreaming}
                  // Round 3: aria-busy tells assistive tech the input is
                  // temporarily unavailable (not broken) during the stream.
                  aria-busy={isStreaming}
                  maxLength={2000}
                  // Density bundle 2026-05-09: textarea text-sm (14px) →
                  // text-[12px] to align with the rest of the chat surface
                  // density. The 14px size felt like a consumer-app input.
                  // Round 3 focus polish: FocusRing.T2_INPUT adds the
                  // :focus-visible variant alongside the existing :focus ring
                  // (the composer keeps its ring on plain click-focus too —
                  // sprint spec §5). Disabled state keeps the platform's
                  // disabled-* tokens (consistent with every other input).
                  className={cn(
                    "flex-1 resize-none rounded-[2px] border border-border bg-muted px-3 py-2 text-[12px] text-foreground placeholder:text-muted-foreground",
                    "focus:outline-none",
                    FocusRing.T2_INPUT,
                    "disabled:cursor-not-allowed disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]",
                  )}
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

              {/* Round 1 Foundation: counter now appears from 800 chars (was
                  1500). WHY 800: at 1500 the user was 75% of the way to the
                  2000 hard cap before getting ANY feedback — long research
                  prompts hit the maxLength wall by surprise. 800 gives the
                  warning at 40%, early enough to restructure the question.
                  WHY font-mono: numeric — ADR-F-15 mandates mono for all
                  numerics. aria-live so screen readers hear the count appear. */}
              {input.length >= 800 && (
                <p
                  aria-live="polite"
                  className="mt-1 font-mono text-[10px] text-muted-foreground"
                >
                  {input.length} / 2000
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {/* ════════════════ CONTEXT RAIL — Entity / Citations / Tickers ════════ */}
      {/*
       * WHY conditional render (not CSS width=0):
       * When collapsed we unmount entirely rather than setting w-0 + overflow-hidden.
       * Unmounting avoids an invisible TanStack Query subscription (the EntityCard
       * inside fires a useQuery). CSS-only hide keeps the query alive, wastes a
       * background refetch every staleTime interval, and would require w-0 on the
       * border-l to avoid a ghost 1px line. Full unmount is simpler and cheaper.
       *
       * WHY border-l: the visual separator between the message column and the
       * context rail. Matches the border-r on the thread list sidebar for
       * symmetry (both panels separated from the centre by a 1px border).
       */}
      {!isContextRailCollapsed && (
        <div className="w-[320px] shrink-0 border-l border-border overflow-hidden">
          <ChatContextRail
            entityId={entityIdFromUrl}
            messages={localMessages.filter(
              // WHY filter: localMessages is LogEntry[] (Message | SlashTurn).
              // ChatContextRail expects Message[] only. Slash turns have
              // `kind: "slash"` — we drop them here so the prop type is clean.
              // Messages are always real Message objects (role + citations).
              (entry): entry is Parameters<typeof ChatContextRail>[0]["messages"][number] =>
                !("kind" in entry),
            )}
            isCollapsed={isContextRailCollapsed}
            onClose={() => setIsContextRailCollapsed(true)}
            onTickerClick={(ticker) => appendToInput(` $${ticker}`)}
            // Round 2: clicking an Entity Overview mini-card pivots straight
            // to the instrument detail page. The rail passes the RESOLVED
            // ticker (canonical symbol from instrument search), and the
            // /instruments/[ticker] route accepts raw tickers (same pattern
            // as the screener's row click).
            onCardClick={(ticker) => router.push(`/instruments/${ticker}`)}
          />
        </div>
      )}
      </div>{/* end centre+right wrapper */}

      {/* ════════════════ DEBUG — Tool Trace Drawer (?debug=1 + ⌘D) ═══════════ */}
      {/* WHY double gate (isDebug && isTraceOpen): isTraceOpen can only become
          true while isDebug is set (the chord hook is inert otherwise), but the
          explicit isDebug check makes the security invariant local and obvious:
          this surface NEVER renders without ?debug=1 (PRD-0089 Q-8). */}
      {isDebug && isTraceOpen && (
        <ToolTraceDrawer trace={toolTrace} onClose={closeTrace} />
      )}
    </div>
  );
}
