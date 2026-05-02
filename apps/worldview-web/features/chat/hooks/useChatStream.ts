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
  SlashTurn,
  StreamingMessage,
} from "@/features/chat/lib/types";

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
  const { accessToken, activeThreadId, setActiveThreadId, refetchThreads } =
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

  // ── Refs ────────────────────────────────────────────────────────────────
  // `abortRef` holds the AbortController for the in-flight request so that
  // `cancel()` and the unmount cleanup can both abort the stream without
  // racing each other. We deliberately use a ref (not state) so that
  // overwriting the controller does not trigger re-renders.
  const abortRef = useRef<AbortController | null>(null);

  // Cancel any in-flight stream on unmount. Without this, a fast nav-away
  // would leak a half-read fetch + a setState that fires after unmount,
  // emitting React's "set state on an unmounted component" warning.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
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
      if (!question || streaming || !accessToken) return;

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
      setStreaming({ text: "", active: true });

      try {
        const response = await fetch("/api/v1/chat/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({ message: question, thread_id: threadId }),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(
            `Stream request failed: ${response.status} ${response.statusText}`,
          );
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error(
            "Response body is null — server did not return a stream",
          );
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let finalContent = "";

        // Read loop: SSE frames are newline-delimited; we split on \n,
        // keep the trailing partial in `buffer` for the next pump.
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
              // Normal termination. Promote the streaming bubble to a
              // proper assistant message and refresh the threads list so
              // the sidebar shows the new last_msg_at.
              setStreaming(null);
              if (finalContent) {
                const assistantMessage: Message = {
                  message_id: crypto.randomUUID(),
                  thread_id: threadId,
                  role: "assistant",
                  content: finalContent,
                  created_at: new Date().toISOString(),
                  citations: [],
                };
                setLocalMessages((prev) => [...prev, assistantMessage]);
              }
              refetchThreads();
              return;
            }

            try {
              const parsedToken = JSON.parse(payload) as {
                text?: string;
                token?: string;
              };
              const chunk = parsedToken.text ?? parsedToken.token;
              if (chunk) {
                finalContent += chunk;
                // Functional update: prev may have been replaced by a
                // concurrent setState (e.g. cancel() racing the read loop).
                setStreaming((prev) =>
                  prev ? { ...prev, text: prev.text + chunk } : prev,
                );
              }
            } catch {
              // Non-JSON line — keep-alive comment, blank line, etc. Skip.
            }
          }
        }

        // Reader exhausted without a [DONE] sentinel — server closed early.
        // Preserve whatever tokens we did receive but flag the truncation
        // so the user sees the partial answer is intentional.
        setStreaming(null);
        if (finalContent) {
          const assistantMessage: Message = {
            message_id: crypto.randomUUID(),
            thread_id: threadId,
            role: "assistant",
            content: finalContent + "\n\n[Response interrupted]",
            created_at: new Date().toISOString(),
            citations: [],
          };
          setLocalMessages((prev) => [...prev, assistantMessage]);
        }
      } catch (err) {
        // AbortError is the EXPECTED outcome of cancel() / unmount — it is
        // not an error condition, so we swallow it and only clear the
        // streaming bubble.
        if (err instanceof Error && err.name === "AbortError") {
          setStreaming(null);
          return;
        }
        setStreaming(null);
        setChatError(
          err instanceof Error
            ? err.message
            : "Chat request failed. Please try again.",
        );
      } finally {
        abortRef.current = null;
      }
    },
    [accessToken, activeThreadId, refetchThreads, setActiveThreadId, streaming],
  );

  return {
    localMessages,
    setLocalMessages,
    streaming,
    chatError,
    setChatError,
    isStreaming: streaming !== null,
    send,
    cancel,
    resetForThread,
  };
}
