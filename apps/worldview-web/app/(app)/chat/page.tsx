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

import { createGateway } from "@/lib/gateway";
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
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
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

  const { data: activeThread, isLoading: threadLoading } = useQuery<Thread>({
    queryKey: qk.chat.thread(activeThreadId ?? ""),
    queryFn: () => createGateway(accessToken).getThread(activeThreadId!),
    enabled: !!accessToken && !!activeThreadId,
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
    setActiveThreadId(newId);
    resetForThread();
    setInput("");
  }, [resetForThread]);

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
          setActiveThreadId(null);
          resetForThread();
        }
        void refetchThreads();
      } catch {
        // Silently fail — the thread may already be gone.
      }
    },
    [accessToken, activeThreadId, refetchThreads, resetForThread],
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
