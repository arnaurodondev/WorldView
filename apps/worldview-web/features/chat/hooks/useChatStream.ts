/**
 * features/chat/hooks/useChatStream.ts — Encapsulates the SSE chat streaming
 * lifecycle for the Intelligence Chat page.
 *
 * WHY THIS HOOK EXISTS (PLAN-0059 E-3 follow-up):
 * The chat page (`app/(app)/chat/page.tsx`) had grown to ~916 LOC. The single
 * largest concern there was the SSE send/stream/abort flow (~150 LOC of
 * dense logic intermixed with view code). Lifting it into a hook:
 *
 *   1. Shrinks the page below the 700-LOC institutional ceiling we picked in
 *      PLAN-0059 §7 (E-3) — view code stays focused on layout & event wiring.
 *   2. Makes the SSE flow independently testable. Driving a hook with
 *      `renderHook` + a mocked `fetch` is dramatically easier than spinning
 *      up the whole chat page (with ScrollArea / Radix portals / TanStack
 *      Query providers) just to assert a [DONE] sentinel resets streaming.
 *   3. Pins the wire-format contract in one place: the backend (S8 / S9)
 *      emits `data: {...}\n` lines + a final `data: [DONE]\n`. Centralising
 *      the parser keeps a single source of truth.
 *
 * BEHAVIOUR PARITY GUARANTEE: every observable behaviour from the inline
 * page implementation is preserved verbatim — same wire request, same
 * abort-error swallowing, same "[Response interrupted]" suffix on early
 * EOF, same `crypto.randomUUID()` thread auto-creation, same
 * `refetchThreads()` invalidation after [DONE]. See the chat page git
 * history for the original block.
 *
 * WHY NOT EventSource: the SSE endpoint is `POST /api/v1/chat/stream` with a
 * JSON body. EventSource only supports GET, so we hand-roll the SSE parser
 * over `fetch().body.getReader()` + `TextDecoder`.
 */

"use client";
// WHY "use client": this hook drives mutable React state, refs, and the
// browser-only fetch streaming API. None of that runs in a server component.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { parseInput } from "@/lib/chat/slash-commands";
import type { Message } from "@/types/api";
import type {
  LogEntry,
  PendingActionEvent,
  SlashTurn,
  StreamingMessage,
} from "@/features/chat/lib/types";
// WHY import from ToolCallIndicator (not defined here):
// ToolCallState is the view-model type for tool progress — it lives in the
// component layer so the component file is the single canonical definition.
// The hook imports from there (not vice versa) because the hook feeds the
// component, not the other way round.
import type { ToolCallState } from "@/features/chat/components/ToolCallIndicator";

// ── Public hook contract ──────────────────────────────────────────────────────

/**
 * Inputs the page wires into the hook.
 *
 * WHY pass `setActiveThreadId` rather than read it back: when the user sends
 * the first message in a fresh session there's no thread yet — the hook
 * mints a UUID (matching server expectation: client-assigned thread ids)
 * and tells the page which thread is now active. Centralising the call
 * here guarantees the page never sends a request without a thread id.
 */
export interface UseChatStreamArgs {
  /** Bearer token from `useAuth`. When null, sends are no-ops. */
  accessToken: string | null;
  /** Currently selected thread id, or null for "new chat" state. */
  activeThreadId: string | null;
  /** Promote a freshly-minted thread id to the page-level state. */
  setActiveThreadId: (id: string) => void;
  /**
   * Refetch the threads list once a stream completes so the sidebar shows
   * the new thread (or refreshes the `last_msg_at` of an existing one).
   */
  refetchThreads: () => void;
  /**
   * Optional entity ID for the intelligence page chat panel (A-3 ADR).
   *
   * WHY a single hook option instead of a parallel hook:
   * The SSE parsing, abort handling, streaming state, and tool event demux
   * logic are identical for both the main chat and the entity-scoped chat.
   * Creating a parallel hook would duplicate ~400 LOC of tested logic with
   * subtle divergence risk. A single boolean-ish option keeps one path
   * through the code and one set of tests. Callers that don't set entityId
   * get the original /api/v1/chat/stream endpoint unchanged.
   *
   * WHEN SET: uses POST /api/v1/chat/entity-context instead of
   * POST /api/v1/chat/stream, and includes `entity_id` in the request body.
   * This lets S8 scope its RAG retrieval to evidence/relations for that entity.
   *
   * ANCHOR vs SELECTED: the EntityChatPanel always passes `anchorEntityId`
   * (the route param), NOT selectedEntityId — chat is scoped to the entity
   * the user navigated to, not the node they last clicked in the graph.
   */
  entityId?: string;
}

/**
 * Outputs returned from the hook. Page calls `send()` and `cancel()` and
 * reads the streaming/error state into the JSX.
 *
 * WHY expose `setLocalMessages`: the page also has a TanStack Query
 * subscription on the active thread that needs to seed the local message
 * log when the user switches threads. The query lives at the page level
 * (it depends on the page-level QueryClient), so it must hand the data
 * back through this setter. Same reasoning for `setChatError` — the page
 * sometimes wants to clear the error on user gesture (e.g. selecting
 * another thread).
 */
export interface UseChatStreamResult {
  localMessages: LogEntry[];
  setLocalMessages: Dispatch<SetStateAction<LogEntry[]>>;
  streaming: StreamingMessage | null;
  chatError: string | null;
  setChatError: (e: string | null) => void;
  isStreaming: boolean;
  /**
   * Active tool calls for the current streaming response (PLAN-0067 W11-5).
   * Each entry tracks one tool's progress: running → ok/empty/error.
   * Cleared to [] when the stream ends or is cancelled.
   */
  activeTools: ToolCallState[];
  /**
   * Pending write-action event waiting for user confirmation (PLAN-0082 Wave B).
   * Set when the backend emits a ``pending_action`` SSE event.
   * Cleared to null after the user confirms or dismisses the modal.
   *
   * WHY state (not ref): the chat page reads this to conditionally render the
   * ActionConfirmModal. React must re-render when this value changes.
   */
  pendingAction: PendingActionEvent | null;
  /** Clear the pending action (called by ActionConfirmModal on dismiss or after confirm). */
  clearPendingAction: () => void;
  /** Trigger the slash-command branch or the SSE LLM call for `question`. */
  send: (question: string) => Promise<void>;
  /** Abort an in-flight stream. Safe to call when nothing is streaming. */
  cancel: () => void;
  /**
   * Reset all local state for a fresh thread (clear messages, abort any
   * in-flight stream, clear error). The page calls this when the user
   * clicks "New chat" or selects a different thread.
   */
  resetForThread: () => void;
}

// ── Implementation ────────────────────────────────────────────────────────────

export function useChatStream(args: UseChatStreamArgs): UseChatStreamResult {
  const { accessToken, activeThreadId, setActiveThreadId, refetchThreads, entityId } =
    args;

  // ── State ───────────────────────────────────────────────────────────────
  // `localMessages` — the rendered conversation log. We keep it local
  // (not pure TanStack cache) because we mutate it optimistically with the
  // user message, the in-flight tokens, and the final assistant message
  // BEFORE the server has acknowledged any of them.
  const [localMessages, setLocalMessages] = useState<LogEntry[]>([]);
  // `streaming` — transient bubble shown while tokens arrive. Null when
  // idle. The page renders a typing indicator while text === "".
  const [streaming, setStreaming] = useState<StreamingMessage | null>(null);
  // `chatError` — surfaced as a destructive banner under the message list.
  // Null when no error or after an explicit clear.
  const [chatError, setChatError] = useState<string | null>(null);
  // `activeTools` — per-tool progress for the current streaming response.
  // Populated by `tool_call` SSE events, updated by `tool_result` events,
  // cleared when the stream ends or is cancelled.
  // WHY state (not ref): the chat page reads this to pass down to ToolCallIndicator;
  // we need React to re-render on every tool status change.
  const [activeTools, setActiveTools] = useState<ToolCallState[]>([]);
  // `pendingAction` — set when the backend emits a `pending_action` SSE event
  // for a write-action tool (e.g. create_alert). The page renders an
  // ActionConfirmModal when this is non-null. Cleared to null on dismiss/confirm.
  // WHY state (not ref): the page must re-render when this changes so the
  // modal appears/disappears. A ref would not trigger a re-render.
  const [pendingAction, setPendingAction] = useState<PendingActionEvent | null>(null);

  // ── Refs ────────────────────────────────────────────────────────────────
  // `abortRef` holds the AbortController for the in-flight request so that
  // `cancel()` and the unmount cleanup can both abort the stream without
  // racing each other. We deliberately use a ref (not state) so that
  // overwriting the controller does not trigger re-renders.
  const abortRef = useRef<AbortController | null>(null);

  // WHY isStreamingRef: `streaming` state in useCallback closures is a stale
  // snapshot — programmatic double-send sees streaming=null in both closures and
  // passes the guard twice, orphaning the first AbortController. The ref is
  // always current so the guard is race-free regardless of batching semantics.
  const isStreamingRef = useRef(false);

  // Cancel any in-flight stream on unmount. Without this, a fast nav-away
  // would leak a half-read fetch + a setState that fires after unmount,
  // emitting React's "set state on an unmounted component" warning.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  /**
   * `clearPendingAction` — called by ActionConfirmModal when the user
   * confirms or dismisses the pending write-action.  Resets the state so
   * the modal closes and React re-renders without a pending action.
   *
   * WHY a stable callback (not inline setState): ActionConfirmModal is a
   * memoised component that receives this as a prop.  A stable reference
   * prevents unnecessary re-renders of the modal tree.
   */
  const clearPendingAction = useCallback(() => {
    setPendingAction(null);
  }, []);

  /**
   * `cancel` — user-initiated stop. Mirrors the previous page-level
   * `handleCancelStream`. Clears the streaming bubble; the in-flight
   * fetch's `catch` branch swallows the AbortError silently so we don't
   * surface a false "request failed" to the user.
   */
  const cancel = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStreaming(null);
    // WHY clear here: if the user cancels mid-tool-use, the tool indicators
    // would stay frozen on screen with spinners. Clearing them on cancel
    // ensures no stale tool state persists after the stream is aborted.
    setActiveTools([]);
  }, []);

  /**
   * `resetForThread` — switch to a different thread (or "New chat"). We
   * abort the in-flight stream so it doesn't write tokens into the new
   * thread's log, then clear all transient state.
   */
  const resetForThread = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStreaming(null);
    setChatError(null);
    setLocalMessages([]);
    // WHY clear activeTools here: if a tool-use stream was in progress when
    // the user switched threads, the tool spinners would remain frozen in the
    // UI for the new thread until its own stream started. Clearing them in
    // resetForThread ensures the new thread always starts with a clean tool
    // indicator state, matching the post-stream/post-cancel invariant.
    setActiveTools([]);
    // WHY clear pendingAction here: a pending confirmation modal must not
    // persist across thread switches — the proposal_id is scoped to the
    // thread that generated it. If the user switches threads, dismiss the modal.
    setPendingAction(null);
  }, []);

  /**
   * `send` — the heart of the hook. Branches into:
   *
   *   1. Slash-command short-circuit (PLAN-0051 T-E-5-01): if the input
   *      parses as a structured command (e.g. `/quote AAPL`) we render
   *      it as a SlashTurn and skip the LLM round-trip entirely.
   *   2. Standard LLM path: POST + SSE reader loop, with token chunks
   *      ({"text": "..."} or {"token": "..."}) accumulated into a final
   *      assistant message.
   *
   * WHY POST + fetch (not EventSource): EventSource is GET-only and we
   * need to send a JSON body ({message, thread_id}). We therefore consume
   * the SSE stream manually via `response.body.getReader()`.
   *
   * WHY crypto.randomUUID: client-assigned thread ids let streaming begin
   * without an extra `POST /threads` round-trip; the server creates the
   * thread server-side on first chat send if it doesn't exist.
   */
  const send = useCallback(
    async (rawInput: string): Promise<void> => {
      const question = rawInput.trim();
      // Same guards the page used to enforce: empty input, mid-stream,
      // or unauthenticated → silent no-op.
      // WHY isStreamingRef (not streaming state): see isStreamingRef comment above.
      if (!question || isStreamingRef.current || !accessToken) return;

      // ── Slash command short-circuit ───────────────────────────────────
      const parsed = parseInput(question);
      if (parsed) {
        // Auto-create the thread id even on the slash branch so subsequent
        // LLM messages join the same thread. Matches prior behaviour.
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
        setChatError(null);
        return;
      }

      // ── Standard LLM path ────────────────────────────────────────────
      let threadId = activeThreadId;
      if (!threadId) {
        threadId = crypto.randomUUID();
        setActiveThreadId(threadId);
      }

      // Optimistically append the user bubble before the request fires —
      // perceived-latency win.
      const userMessage: Message = {
        message_id: crypto.randomUUID(),
        thread_id: threadId,
        role: "user",
        content: question,
        created_at: new Date().toISOString(),
        citations: [],
      };
      setLocalMessages((prev) => [...prev, userMessage]);
      setChatError(null);

      const controller = new AbortController();
      abortRef.current = controller;
      isStreamingRef.current = true;
      setStreaming({ text: "", active: true });

      // `reader` declared outside try so the finally block can cancel it
      // on all exit paths (done / [DONE] / error / exception / abort).
      // WHY reader.cancel() matters: without it the ReadableStream stays locked
      // after early return, preventing the connection from returning to the pool.
      let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
      try {
        // WHY entity-context endpoint when entityId set:
        // /api/v1/chat/entity-context scopes S8's RAG retrieval to evidence,
        // relations, and narratives for the specific entity. The main
        // /api/v1/chat/stream uses the full knowledge graph without entity
        // scoping. Using a separate endpoint (not a query param) keeps the
        // two search strategies cleanly separated on the backend. The request
        // body includes entity_id so S8 can pre-filter its vector search.
        const chatEndpoint = entityId
          ? "/api/v1/chat/entity-context"
          : "/api/v1/chat/stream";
        const chatBody: Record<string, unknown> = { message: question, thread_id: threadId };
        if (entityId) chatBody.entity_id = entityId;

        const response = await fetch(chatEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify(chatBody),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            `Stream request failed: ${response.status} ${response.statusText}`,
          );
        }

        reader = response.body?.getReader() ?? null;
        if (!reader) {
          throw new Error(
            "Response body is null — server did not return a stream",
          );
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let finalContent = "";
        // SSE events carry an optional `event:` field before their `data:` line.
        // We track the pending event name so each data payload is routed correctly.
        let pendingEventName = "";
        // Citations received via the `citations` SSE event, applied to the
        // final assistant message once the stream ends.
        let pendingCitations: Message["citations"] = [];

        // Helper: finalise the stream and promote the bubble to a message.
        const finalize = (interrupted = false) => {
          setStreaming(null);
          if (finalContent || pendingCitations.length > 0) {
            const assistantMessage: Message = {
              message_id: crypto.randomUUID(),
              thread_id: threadId,
              role: "assistant",
              content: interrupted
                ? finalContent + "\n\n[Response interrupted]"
                : finalContent,
              created_at: new Date().toISOString(),
              citations: pendingCitations,
            };
            setLocalMessages((prev) => [...prev, assistantMessage]);
          }
          refetchThreads();
        };

        // Read loop: SSE frames are newline-delimited; we split on \n,
        // keep the trailing partial in `buffer` for the next pump.
        // Each SSE event may have an `event:` field before its `data:` line.
        // We read both so we can demultiplex token/citations/done/error events.
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            // Capture the event type for the next data line.
            if (line.startsWith("event: ")) {
              pendingEventName = line.slice(7).trim();
              continue;
            }

            if (!line.startsWith("data: ")) continue;
            const payload = line.slice(6);

            // Consume and reset the pending event name for this data line.
            const eventName = pendingEventName;
            pendingEventName = "";

            // `done` event: backend signals clean end-of-stream.
            // WHY clear activeTools here: tools should not linger in the UI
            // after the answer is fully rendered. The `finalize()` call sets
            // streaming=null; clearning tools at the same time keeps the two
            // states in sync (both reset together at stream end).
            if (eventName === "done") {
              setActiveTools([]);
              finalize();
              return;
            }

            // Legacy [DONE] sentinel — backward compat with older backends.
            if (payload === "[DONE]") {
              // WHY clear here too: same reason as the `done` event handler above.
              // Both end-of-stream paths must reset tool indicators.
              setActiveTools([]);
              finalize();
              return;
            }

            try {
              const data = JSON.parse(payload) as Record<string, unknown>;

              // ── Tool-use events (PLAN-0067 W11-5) ──────────────────────────
              // These three event types are emitted by SSEEmitter during the
              // tool-use phase (before any token chunks arrive). They drive
              // ToolCallIndicator in the streaming bubble.

              if (eventName === "thinking") {
                // `thinking` — the LLM is classifying the query and deciding
                // which tools to invoke. No UI state change needed here; the
                // typing indicator (shown when streaming.text === "") already
                // signals "I'm working on it". Future: could set a global
                // "Thinking..." banner if desired.
                // WHY no-op: the TypingIndicator already covers the blank-stream
                // phase. Adding a separate "thinking" indicator would duplicate
                // the feedback and add visual noise.
                void data; // suppress "unused" lint warning
              } else if (eventName === "tool_call") {
                // `tool_call` — a specific tool has been invoked. The data shape
                // from S8 SSEEmitter (W11-3):
                //   { type: "tool_call", tool: string, label: string, input: {}, status: "running" }
                // We only use `tool`, `label`, and `status` for rendering.
                const tc = data as { tool?: string; label?: string; status?: string };
                if (tc.tool && tc.label) {
                  setActiveTools((prev) => [
                    // Replace any existing entry for the same tool name (idempotent).
                    // WHY filter first: the backend could emit duplicate tool_call
                    // events if the tool is retried; we don't want duplicate rows.
                    ...prev.filter((t) => t.name !== tc.tool),
                    {
                      name: tc.tool as string,
                      label: tc.label as string,
                      status: "running",
                    },
                  ]);
                }
              } else if (eventName === "tool_result") {
                // `tool_result` — a tool has completed. The data shape from S8:
                //   { type: "tool_result", tool: string, status: "ok"|"empty"|"error", item_count: number }
                // We map the status onto the existing ToolCallState entry.
                const tr = data as { tool?: string; status?: string };
                if (tr.tool && tr.status) {
                  const resultStatus = (tr.status as ToolCallState["status"]) ?? "error";
                  setActiveTools((prev) =>
                    prev.map((t) =>
                      t.name === tr.tool
                        ? { ...t, status: resultStatus }
                        : t,
                    ),
                  );
                }
              } else if (eventName === "pending_action") {
                // PLAN-0082 Wave B: write-action tool requires user confirmation.
                // The backend emits this event when the LLM calls create_alert
                // (or any future requires_confirmation=true tool).
                //
                // Data shape from S8 SSEEmitter (Wave B):
                //   { type: "pending_action", proposal_id: string, tool: string,
                //     description: string, params: { entity_id?, condition?,
                //     threshold?, severity? } }
                //
                // WHY set state from SSE: the modal must appear immediately when
                // the pending_action event arrives, before the stream ends.  We
                // set it here in the read loop so the React render triggers
                // promptly.  The modal will render on the next frame.
                const pa = data as {
                  proposal_id?: string;
                  tool?: string;
                  description?: string;
                  params?: Record<string, unknown>;
                };
                if (pa.proposal_id && pa.tool) {
                  setPendingAction({
                    proposal_id: pa.proposal_id,
                    tool: pa.tool,
                    description: pa.description ?? `Create alert: ${pa.params?.condition ?? "?"}`,
                    params: pa.params ?? {},
                  });
                }
              } else if (
                eventName === "action_executed" ||
                eventName === "action_rejected"
              ) {
                // PLAN-0082 Wave B: confirmation endpoint response events.
                // These arrive on the SEPARATE confirm SSE stream (not the chat
                // stream), so in practice this branch is unreachable from the
                // chat stream reader loop.  We handle them here defensively in
                // case S8 ever emits them inline, and to silence the linter
                // warning about unhandled known event names.
                //
                // WHY clear pendingAction on executed/rejected: if the confirm
                // stream somehow feeds back into the same hook (future multi-turn
                // flow), the modal should auto-dismiss on both outcomes.
                setPendingAction(null);
              } else if (
                eventName === "token" ||
                (!eventName && ("text" in data || "token" in data))
              ) {
                // Token chunk — append to the streaming bubble immediately.
                const chunk = (data.text ?? data.token) as string | undefined;
                if (chunk) {
                  finalContent += chunk;
                  // Functional update: prev may have been replaced by a
                  // concurrent setState (e.g. cancel() racing the read loop).
                  setStreaming((prev) =>
                    prev ? { ...prev, text: prev.text + chunk } : prev,
                  );
                }
              } else if (eventName === "citations") {
                // WHY validate before accepting: the data is from an SSE frame
                // over a server-controlled stream. A compromised S8 backend could
                // inject citations with javascript: URLs that CitationList renders
                // as <a href>. We accept objects with either:
                //   (a) a valid https?:/mailto: URL (external news/web sources), OR
                //   (b) url=null/undefined (knowledge-graph tool results such as
                //       get_entity_graph, search_claims, get_contradictions, etc.)
                // WHY allow null URL: KG citations have no hyperlink to follow —
                // they reference in-platform graph data. Previously filtering them
                // out caused ALL KG-sourced citations to be silently dropped.
                // URL-safety enforcement now lives in the rendering layer: the
                // CitationList component renders KG citations as plain text (no
                // <a> tag) when url is null/undefined.
                if (Array.isArray(data)) {
                  pendingCitations = data.filter(
                    (c): c is NonNullable<Message["citations"]>[number] => {
                      if (typeof c !== "object" || c === null) return false;
                      const url = (c as Record<string, unknown>).url;
                      // Accept citations without a URL (knowledge-graph sources).
                      if (url === null || url === undefined) return true;
                      // For citations that DO have a URL, enforce the safe-protocol
                      // check to block javascript:/data: injection vectors.
                      return (
                        typeof url === "string" &&
                        /^(https?:|mailto:)/i.test(url)
                      );
                    },
                  );
                }
              } else if (eventName === "error") {
                const msg =
                  typeof data.message === "string"
                    ? data.message
                    : "Stream error from server";
                setChatError(msg);
                setStreaming(null);
                return;
              }
              // status, contradictions, metadata — no UI action needed yet;
              // accepted silently so the parser never throws on them.
            } catch {
              // Non-JSON line — keep-alive comment, blank line, etc. Skip.
            }
          }
        }

        // Reader exhausted without a `done` event — server closed early.
        // Preserve whatever tokens we did receive but flag the truncation.
        finalize(/* interrupted */ finalContent.length > 0);
      } catch (err) {
        // AbortError is the EXPECTED outcome of cancel() / unmount — it is
        // not an error condition, so we swallow it and only clear the
        // streaming bubble.
        if (err instanceof Error && err.name === "AbortError") {
          setStreaming(null);
          return;
        }
        setStreaming(null);
        // WHY map to generic message: raw err.message can contain internal
        // hostnames, HTTP response bodies, or status text leaked by reverse
        // proxies. These would surface in error-monitoring SDKs (Sentry, Datadog)
        // as PII/infra details. We map known error codes to safe user-facing strings.
        const statusMatch =
          err instanceof Error ? err.message.match(/^Stream request failed: (\d+)/) : null;
        const statusCode = statusMatch ? parseInt(statusMatch[1], 10) : 0;
        setChatError(
          statusCode === 401
            ? "Session expired — please sign in again."
            : statusCode >= 500
              ? "Server error — please try again."
              : statusCode > 0
                ? "Request failed — please try again."
                : "Chat request failed. Please try again.",
        );
      } finally {
        isStreamingRef.current = false;
        abortRef.current = null;
        // WHY reader.cancel(): releases the ReadableStream lock so the
        // underlying network connection returns to the pool. Without this,
        // each early return (done/[DONE]/error/abort) leaves the stream locked.
        if (reader) {
          reader.cancel().catch(() => {
            // cancel() can throw if the stream is already errored — swallow silently.
          });
        }
      }
    },
    // WHY no `streaming` dep: we read isStreamingRef.current for the guard
    // (ref-based, always current) so the closure doesn't need to re-bind.
    // WHY entityId in deps: when entityId changes (e.g. sidebar sync switches
    // the anchor), the endpoint changes — the closure must re-bind to pick it up.
    [accessToken, activeThreadId, refetchThreads, setActiveThreadId, entityId],
  );

  return {
    localMessages,
    setLocalMessages,
    streaming,
    chatError,
    setChatError,
    isStreaming: streaming !== null,
    // PLAN-0067 W11-5: exposed so the chat page can pass it down to
    // StreamingBubble → ToolCallIndicator. Empty array when not streaming.
    activeTools,
    send,
    cancel,
    resetForThread,
  };
}
