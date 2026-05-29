/**
 * app/(app)/chat/page.tsx — Intelligence / Chat page (PLAN-0089 K T-20.5 rewrite)
 *
 * Research-grade RAG chat. Persistent threads survive across sessions so the
 * analyst can build on prior context. This file is the composition root for
 * Wave K's new flat-turn experience — three columns (thread rail | message
 * column | context rail). PLAN-0089 K T-20.5 dropped the file from ~1200 LOC
 * to ~330 by extracting every visual / state-machine concern into dedicated
 * components under `features/chat/`. The page now owns only:
 *   1. Auth + URL-param resolution (entity_id → ticker).
 *   2. Thread CRUD (list / select / rename / delete / create).
 *   3. Composition of the Wave K components inside `<ChatLayout>`.
 *
 * SSE streaming + slash-command parsing + tool-call demux live in
 * `useChatStream`. The page just calls `send()` and reads view state.
 *
 * DATA SOURCES (all via S9): GET /v1/threads, GET /v1/threads/:id,
 *   PATCH /v1/threads/:id, POST /v1/chat/stream.
 * DESIGN: docs/designs/0089/10-chat-ai.md §3 (3-col layout) + §5 (flat turn).
 */

"use client";
// "use client" because TanStack Query subscriptions, useChatStream's SSE
// reader, useDebugFlag's search-params read, and the ⌘D chord all need the
// browser runtime.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Download } from "lucide-react";

import { createGateway, GatewayError } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// WHY qk.chat.*: removes inline queryKey arrays and the accessToken-in-key
// anti-pattern that caused cache thrashing on OIDC rotation.
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { downloadThread } from "@/lib/chat/export-thread";
import { filterCommands, type SlashCommand } from "@/lib/chat/slash-commands";
import type { Thread, Message } from "@/types/api";

// ── Wave K components (Block B/C/D/E/F) — single source of truth ─────────────
import { ChatLayout } from "@/features/chat/components/ChatLayout";
import { ThreadRail } from "@/features/chat/components/ThreadRail";
import { ChatMessageList } from "@/features/chat/components/ChatMessageList";
import { ChatComposer, type ChatComposerHandle } from "@/features/chat/components/ChatComposer";
import { ChatEmptyState } from "@/features/chat/components/ChatEmptyState";
import { ChatErrorBanner, type ChatError } from "@/features/chat/components/ChatErrorBanner";
import { ChatContextRail } from "@/features/chat/components/ChatContextRail";
import { ToolTraceDrawer, useToolTraceChord } from "@/features/chat/components/ToolTraceDrawer";
import { useDebugFlag } from "@/features/chat/hooks/useDebugFlag";
import { ActionConfirmModal } from "@/features/chat/components/ActionConfirmModal";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import {
  PLACEHOLDER_THREAD_TITLE,
  PORTFOLIO_STARTER_QUESTIONS,
  STARTER_QUESTIONS,
  entityStarters,
} from "@/features/chat/lib/starters";

/**
 * UUID regex used to discriminate `?entity_id=` URL values: a UUIDv7 needs a
 * resolve-to-ticker round-trip; anything else is treated as a literal ticker
 * (legacy callers that pass tickers directly).
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Common English short tokens that match the all-caps ticker shape but are
// definitely not investable tickers. Used by the entity-chip heuristic that
// derives related tickers from user-typed message text.
const TICKER_BLOCKLIST = new Set([
  "I", "A", "AN", "THE", "AND", "OR", "NOT", "FOR", "OF", "IN",
  "ON", "AT", "TO", "BY", "BE", "DO", "IF", "UP", "NO", "VS",
  "AI", "US", "UK", "EU", "Q", "S", "W", "E", "N", "M",
]);

// ── Page component ────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();

  // ── URL param: ?entity_id= → ticker (QA-iter1 MAJ-5) ───────────────────────
  // UUID values get a getCompanyOverview round-trip; non-UUID values are
  // treated as the ticker verbatim (legacy callers). N-MIN-1: never expose
  // the raw UUID in the UI — render "Loading…" while resolving.
  const entityIdFromUrl = searchParams.get("entity_id");
  const looksLikeUuid = !!entityIdFromUrl && UUID_RE.test(entityIdFromUrl);
  const { data: resolvedEntity } = useQuery({
    queryKey: qk.chat.entityResolve(entityIdFromUrl ?? ""),
    enabled: !!accessToken && looksLikeUuid,
    queryFn: () => createGateway(accessToken).getCompanyOverview(entityIdFromUrl as string),
    staleTime: 5 * 60_000,
  });
  const entityTicker = useMemo<string | null>(() => {
    if (!entityIdFromUrl) return null;
    if (looksLikeUuid) return resolvedEntity?.instrument?.ticker ?? null;
    return entityIdFromUrl;
  }, [entityIdFromUrl, looksLikeUuid, resolvedEntity]);

  // ── Local state ────────────────────────────────────────────────────────────
  const [activeThreadId, setActiveThreadIdState] = useState<string | null>(null);
  const [input, setInput] = useState("");
  // PLAN-0102 W2 BP-FIX: Track thread IDs minted on the client (via
  // crypto.randomUUID) that have NOT YET been persisted server-side.
  //
  // WHY THIS EXISTS: Before this fix, `handleNewChat` and `useChatStream.send`
  // both call `setActiveThreadId(crypto.randomUUID())` immediately so the
  // streaming response can be filed under a stable id.  TanStack Query then
  // sees `activeThreadId` change and fires `GET /v1/threads/{id}` BEFORE the
  // first user message has been persisted by rag-chat — the backend has never
  // heard of this id, so it returns 404 and the UI flashes a generic error
  // banner.  The 404 in the user's report came from exactly this race.
  //
  // WHY a Set (not a bool flag): the user can click "New chat" multiple times
  // in a row before any of those threads gets persisted, so we may have more
  // than one ephemeral id in flight.  A Set models that cleanly.
  //
  // WHY useRef + state mirror: the ref is what the gateway-error swallow logic
  // reads (avoids a stale-closure race when the query fires a millisecond
  // after the setState dispatch).  The state mirror is what re-renders the
  // page so `enabled` flips when the id transitions from ephemeral to
  // persisted.  Both stay in sync via the `markEphemeral` / `markPersisted`
  // helpers below.
  const ephemeralThreadIdsRef = useRef<Set<string>>(new Set());
  const [ephemeralVersion, setEphemeralVersion] = useState(0);
  const markEphemeral = useCallback((id: string) => {
    ephemeralThreadIdsRef.current.add(id);
    setEphemeralVersion((v) => v + 1);
  }, []);
  const markPersisted = useCallback((id: string) => {
    if (ephemeralThreadIdsRef.current.delete(id)) {
      setEphemeralVersion((v) => v + 1);
    }
  }, []);
  // WHY a wrapper around setActiveThreadIdState: useChatStream calls
  // setActiveThreadId() when it mints a new thread on the first message of a
  // brand-new session (no prior `handleNewChat`).  We need to mark that id as
  // ephemeral too — otherwise the same race re-appears.  Detect "this id is
  // new to us" by comparing against the current activeThreadId; anything that
  // is neither the current id nor present in `threads` (the server list) is
  // assumed to be a fresh client-side mint.
  const setActiveThreadId = useCallback(
    (id: string) => {
      // Defer the threads-list lookup to render time; here we just need to
      // know whether this id was generated by us.  If it doesn't equal the
      // current id and the caller is `useChatStream.send`, we conservatively
      // mark it ephemeral — `markPersisted` runs once the backend confirms
      // it on the next `refetchThreads`.
      setActiveThreadIdState((prev) => {
        if (prev !== id) {
          // Only mark ephemeral when the id is not already known to the
          // server (avoids redundantly suppressing a real thread fetch).
          const known = threadsRef.current?.some((t) => t.thread_id === id);
          if (!known) markEphemeral(id);
        }
        return id;
      });
    },
    [markEphemeral],
  );
  // Stable ref to the threads list — read by setActiveThreadId without
  // forcing the callback to re-bind every time the list refetches.
  const threadsRef = useRef<Thread[] | undefined>(undefined);
  // Imperative focus() handle on the composer textarea — used after a slash
  // command pick so the user can keep typing immediately.
  const composerRef = useRef<ChatComposerHandle | null>(null);
  // ToolTraceDrawer (Q-8): ⌘D chord registered only when ?debug=1 is on URL.
  const [traceDrawerOpen, setTraceDrawerOpen] = useState(false);
  const isDebug = useDebugFlag();
  useToolTraceChord(isDebug, setTraceDrawerOpen);

  // ── TanStack Query subscriptions ───────────────────────────────────────────
  const {
    data: threads,
    isLoading: threadsLoading,
    error: threadsError,
    refetch: refetchThreads,
  } = useQuery<Thread[]>({
    queryKey: qk.chat.threads(),
    queryFn: () => createGateway(accessToken).getThreads(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // Keep the threads ref synced for setActiveThreadId's "is this id new?" check.
  // WHY useEffect (not useMemo): we read threads in an event-handler context
  // (the setState updater inside setActiveThreadId), so a ref is the safe
  // way to bridge render data into imperative code without re-binding.
  useEffect(() => {
    threadsRef.current = threads;
  }, [threads]);

  // Once the threads list refresh shows our ephemeral id is now server-known,
  // promote it out of the ephemeral set so future renders fetch its detail.
  useEffect(() => {
    if (!threads || ephemeralThreadIdsRef.current.size === 0) return;
    for (const id of Array.from(ephemeralThreadIdsRef.current)) {
      if (threads.some((t) => t.thread_id === id)) {
        markPersisted(id);
      }
    }
  }, [threads, markPersisted]);

  // PLAN-0102 W2 BP-FIX: gate the per-thread fetch on "thread is persisted".
  // The query stays disabled while the id is still ephemeral (client-minted
  // but never sent to rag-chat), avoiding the 404 spike documented in the
  // user report.  The `ephemeralVersion` read is what makes React re-evaluate
  // `enabled` once the set mutates.
  const isEphemeralActive =
    !!activeThreadId && ephemeralThreadIdsRef.current.has(activeThreadId);
  void ephemeralVersion; // dependency tracking only

  const { data: activeThread, isLoading: threadLoading } = useQuery<Thread>({
    queryKey: qk.chat.thread(activeThreadId ?? ""),
    queryFn: async () => {
      try {
        return await createGateway(accessToken).getThread(activeThreadId!);
      } catch (err) {
        // Defensive: even with the ephemeral gate above, a stale localStorage
        // entry / browser-back navigation / cache-restore could land us on a
        // thread id the backend has since deleted.  Treat 404 as "thread does
        // not exist yet" — return an empty in-memory stub so the message
        // column renders gracefully instead of showing the error banner.
        if (err instanceof GatewayError && err.status === 404) {
          // Mark as ephemeral so we stop hammering the endpoint.
          markEphemeral(activeThreadId!);
          return {
            thread_id: activeThreadId!,
            title: null,
            owner_id: "",
            messages: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          } satisfies Thread;
        }
        throw err;
      }
    },
    enabled: !!accessToken && !!activeThreadId && !isEphemeralActive,
    staleTime: 30_000,
  });

  // ── SSE chat stream — useChatStream owns send/abort/parse; page wires it. ─
  const {
    localMessages,
    setLocalMessages,
    streaming,
    chatError,
    isStreaming,
    activeTools,
    pendingAction,
    clearPendingAction,
    send,
    cancel: handleCancelStream,
    resetForThread,
  } = useChatStream({
    accessToken,
    activeThreadId,
    setActiveThreadId,
    refetchThreads: () => void refetchThreads(),
  });

  // FR-5.1 (HIGH-010): sync authoritative thread history → localMessages
  // whenever the TanStack query resolves. The hook's isStreamingRef blocks
  // concurrent send() calls, so this is safe even just after a stream ends.
  useEffect(() => {
    if (activeThread && activeThread.thread_id === activeThreadId) {
      setLocalMessages(activeThread.messages);
    }
  }, [activeThread, activeThreadId, setLocalMessages]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleNewChat = useCallback(() => {
    const newId = crypto.randomUUID();
    // BP-FIX: mark the freshly-minted id as ephemeral BEFORE we set it active
    // so the activeThread query never fires `GET /v1/threads/{newId}` until
    // rag-chat has persisted the thread (i.e. after the first message).
    markEphemeral(newId);
    setActiveThreadIdState(newId);
    resetForThread();
    setInput("");
  }, [resetForThread, markEphemeral]);

  const handleSelectThread = useCallback(
    (threadId: string) => {
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
          // WHY setActiveThreadIdState (raw setter, not the wrapper):
          // the wrapper signature expects a string id (used by useChatStream
          // when minting a fresh id).  Clearing on delete uses the raw
          // setter — there is no new id to mark ephemeral.
          setActiveThreadIdState(null);
          // Also drop the deleted id from the ephemeral set if it was there.
          markPersisted(threadId);
          resetForThread();
        }
        void refetchThreads();
      } catch {
        // Silently fail — the thread may already be gone.
      }
    },
    [accessToken, activeThreadId, refetchThreads, resetForThread, markPersisted],
  );

  // Optimistic rename (PLAN-0051 T-E-5-06): PATCH cache → server → rollback.
  const handleRenameThread = useCallback(
    async (threadId: string, newTitle: string) => {
      const prev = queryClient.getQueryData<Thread[]>(qk.chat.threads());
      if (prev) {
        queryClient.setQueryData<Thread[]>(
          qk.chat.threads(),
          prev.map((t) => (t.thread_id === threadId ? { ...t, title: newTitle } : t)),
        );
      }
      try {
        await createGateway(accessToken).updateThread(threadId, { title: newTitle });
        void refetchThreads();
      } catch (err) {
        if (prev) queryClient.setQueryData(qk.chat.threads(), prev);
        throw err;
      }
    },
    [accessToken, queryClient, refetchThreads],
  );

  // Export the active thread as Markdown. Slash turns become synthetic user
  // Messages — their cards have no value in a `.md` file.
  const handleExport = useCallback(() => {
    if (!activeThread) return;
    const messageList: Message[] = localMessages.flatMap((entry): Message[] => {
      if ("kind" in entry && entry.kind === "slash") {
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

  // Clear the textarea the moment the user hits Enter (UX expectation), then
  // delegate to the hook's send().
  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question) return;
    setInput("");
    await send(question);
  }, [input, send]);

  // P2C-3 related-ticker chips: scan user messages for ticker-shaped tokens
  // (1–5 char all-caps, blocklist filtered) and surface up to 5 as chips
  // above the textarea. Chips append `$TICKER` to the input.
  const relatedChips = useMemo(() => {
    if (!activeThreadId || localMessages.length === 0) return [];
    const TICKER_RE = /\b([A-Z]{1,5})\b/g;
    const seen = new Set<string>();
    for (const entry of localMessages) {
      if ("kind" in entry) continue; // skip slash turns
      const msg = entry as { role: string; content: string };
      if (msg.role !== "user") continue;
      let m: RegExpExecArray | null;
      const re = new RegExp(TICKER_RE.source, "g");
      while ((m = re.exec(msg.content)) !== null) {
        const tok = m[1];
        if (!TICKER_BLOCKLIST.has(tok) && tok.length >= 2) seen.add(tok);
      }
    }
    if (entityTicker) seen.add(entityTicker);
    return Array.from(seen)
      .slice(0, 5)
      // Append "$TICKER" with a leading space so chips don't glue to the
      // previous word; trimEnd guards against double spaces.
      .map((ticker) => ({
        ticker,
        onPick: () =>
          setInput((prev) => {
            const trimmed = prev.trimEnd();
            return trimmed ? `${trimmed} $${ticker}` : `$${ticker}`;
          }),
      }));
  }, [activeThreadId, localMessages, entityTicker]);

  // Slash-command autocomplete. Commands with an arg get a trailing space so
  // the user can type the argument immediately; arg-less commands are
  // dropped inline. filterCommands stays imported as a future hook.
  const showAutocomplete = input.trimStart().startsWith("/") && !input.includes("\n");
  const autocomplete = showAutocomplete
    ? {
        visible: true,
        query: input,
        onPick: (cmd: SlashCommand) => {
          setInput(`/${cmd.name}${cmd.argSpec ? " " : ""}`);
          composerRef.current?.focus();
        },
      }
    : undefined;
  void filterCommands;

  // Last assistant turn — fed to the trace drawer for ⌘D introspection.
  const selectedTurn = useMemo<Message | null>(() => {
    for (let i = localMessages.length - 1; i >= 0; i -= 1) {
      const e = localMessages[i];
      if (!("kind" in e) && (e as Message).role === "assistant") return e as Message;
    }
    return null;
  }, [localMessages]);

  // Error banner: 401 → auth variant; everything else → generic.
  const chatErrorForBanner: ChatError | null = useMemo(() => {
    if (!chatError) return null;
    const lower = chatError.toLowerCase();
    if (lower.includes("401") || lower.includes("unauthor")) return { kind: "auth" };
    return { kind: "generic", message: chatError };
  }, [chatError]);

  // In-thread starter-questions grid (entity-aware).
  const starterGrid = useMemo(() => {
    const list = entityTicker ? entityStarters(entityTicker) : STARTER_QUESTIONS;
    return list.map((q) => (entityTicker ? q : q.replace("[TICKER]", entityTicker ?? "[TICKER]")));
  }, [entityTicker]);

  // Empty-state starter pick: pre-fill input then create the thread.
  const handlePickStarter = useCallback(
    (prompt: string) => {
      setInput(prompt);
      handleNewChat();
    },
    [handleNewChat],
  );

  // Three named slots in <ChatLayout> — the layout owns the 3-col grid + ⌘\ chord.
  return (
    <>
      <ChatLayout
        threadRail={
          <ThreadRail
            threads={threads}
            activeThreadId={activeThreadId}
            isLoading={threadsLoading}
            error={threadsError}
            onRetry={() => void refetchThreads()}
            onNewChat={handleNewChat}
            onSelect={handleSelectThread}
            onDelete={handleDeleteThread}
            onRename={handleRenameThread}
          />
        }
        messageColumn={
          <>
            {/* Welcome panel when no thread is selected. */}
            {!activeThreadId ? (
              <ChatEmptyState
                starters={PORTFOLIO_STARTER_QUESTIONS}
                onPickStarter={handlePickStarter}
                onNewChat={handleNewChat}
              />
            ) : (
              <>
                {/* Active-thread header: title + Export button. */}
                <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
                  <p className="min-w-0 flex-1 truncate text-[12px] font-semibold text-foreground">
                    {activeThread?.title ?? PLACEHOLDER_THREAD_TITLE}
                  </p>
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

                {/* Auth-aware error banner above the list. */}
                {chatErrorForBanner ? (
                  <div className="px-3 pt-2">
                    <ChatErrorBanner error={chatErrorForBanner} />
                  </div>
                ) : null}

                {/* Flat message column (auto-scroll + streaming projection live in the list). */}
                <ChatMessageList
                  messages={localMessages}
                  streaming={streaming}
                  activeTools={activeTools}
                  threadLoading={threadLoading}
                  emptyState={
                    <div className="grid grid-cols-2 gap-2 p-3">
                      {starterGrid.map((q, i) => (
                        <button
                          key={i}
                          type="button"
                          className="rounded-[2px] border border-border bg-card cursor-pointer p-3 text-left hover:border-primary/40 hover:bg-muted/40 text-[11px] leading-relaxed text-foreground transition-colors duration-0"
                          onClick={() => setInput(q)}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  }
                />

                <ChatComposer
                  ref={composerRef}
                  value={input}
                  onChange={setInput}
                  onSend={() => void handleSend()}
                  onCancel={handleCancelStream}
                  isStreaming={isStreaming}
                  canSend={!!accessToken}
                  entityContext={
                    entityIdFromUrl
                      ? {
                          label:
                            entityTicker ?? (looksLikeUuid ? "Loading…" : entityIdFromUrl),
                        }
                      : undefined
                  }
                  relatedChips={relatedChips}
                  autocomplete={autocomplete}
                />
              </>
            )}
          </>
        }
        contextRail={
          <ChatContextRail
            threadId={activeThreadId ?? ""}
            messages={localMessages.filter((e): e is Message => !("kind" in e))}
            activeEntity={
              entityIdFromUrl
                ? { id: entityIdFromUrl, ticker: entityTicker ?? null }
                : null
            }
          />
        }
      />

      {/* PLAN-0082 Wave B write-action confirmation modal (portal'd to body). */}
      <ActionConfirmModal
        pendingAction={pendingAction}
        accessToken={accessToken}
        onDismiss={clearPendingAction}
      />

      {/* Q-8 debug drawer — component self-gates on ?debug=1. */}
      <ToolTraceDrawer
        open={traceDrawerOpen}
        onClose={() => setTraceDrawerOpen(false)}
        turn={selectedTurn}
      />
    </>
  );
}
