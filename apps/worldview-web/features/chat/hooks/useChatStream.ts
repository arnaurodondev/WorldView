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
 * abort-error swallowing, same `crypto.randomUUID()` thread auto-creation,
 * same `refetchThreads()` invalidation after [DONE]. See the chat page git
 * history for the original block.
 *
 * ROUND 4 HARDENING — one deliberate divergence from the original block:
 * reader exhaustion WITHOUT a `done`/[DONE] event (server or network closed
 * the stream early) used to splice a "[Response interrupted]" suffix into the
 * assistant message content and otherwise complete silently. That made a
 * truncated answer read like model output and gave the user no recovery
 * affordance. It now (a) preserves the partial content VERBATIM as its own
 * message, (b) surfaces an explicit interruption notice through `chatError`
 * (rendered as the inline banner under the messages), and (c) arms `retry()`
 * — see the post-read-loop block in send().
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
import { parseSSELine } from "@/lib/sse-parser";
// QA Wave-3 closeout: streamed `citations` events carry the canonical rag-chat
// shape (source_name/confidence/id) — normalize to the legacy Citation contract
// the chat components expect, exactly like getThread() does for persisted
// messages. Without this, CitationList crashes on `cite.source.toLowerCase()`.
import { normalizeCitation } from "@/lib/api/chat";
import type { Message } from "@/types/api";
import type {
  AgentIterationEvent,
  AssistantTurnMeta,
  LogEntry,
  MessageWithMeta,
  PendingActionEvent,
  SlashTurn,
  StreamingMessage,
  ToolTraceEntry,
  ToolUsageSample,
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
  /**
   * Latest `agent_iteration` SSE event (PLAN-0099 W4) — drives the always-visible
   * AgentIterationProgress strip during multi-iteration tool loops.
   *
   * - Null in the initial state (no event received yet) — strip is hidden.
   * - Set on every `agent_iteration` SSE event (planning_tools →
   *   reasoning_over_results → synthesizing) — strip stays visible through
   *   the silent gaps between tool batches.
   * - Cleared to null when the stream completes/cancels/errors — strip
   *   disappears alongside the rest of the streaming chrome.
   *
   * WHY a single "latest" event (not a history array): the UI only renders
   * the current stage. Keeping just the latest avoids unbounded memory growth
   * on long research queries and matches the at-a-glance UX the strip needs.
   */
  iterationEvent: AgentIterationEvent | null;
  /**
   * Debug tool trace for the LAST turn (Round 1 Foundation — ToolTraceDrawer).
   *
   * Unlike `activeTools` (cleared the instant the stream ends so no spinner
   * outlives the response), the trace is deliberately KEPT after completion —
   * the whole point of the ?debug=1 drawer is post-hoc inspection of which
   * tools ran, with what JSON arguments, what they returned, and how long
   * each took. Reset at the start of the next send and on thread switch.
   */
  toolTrace: ToolTraceEntry[];
  /**
   * Phase-1 Research timeline: TRUE while the backend is in the post-synthesis
   * grounding-validation / repair phase (the `status` event with
   * step="verifying"). The Research timeline renders a "Verifying answer
   * against sources…" line during this window. Reset to false at the start of
   * each send and when the stream settles/cancels/errors.
   *
   * WHY state (not ref): the timeline must re-render the verify line the moment
   * the event lands — a ref would not trigger that render.
   */
  verifying: boolean;
  /**
   * Server-generated follow-up suggestions for the LAST settled turn
   * (frontend-rework Wave 2 — `suggestions` SSE event, Wave-1 backend).
   *
   * Wire shape: a bare JSON string array emitted AFTER the final token
   * (verified live: `event: suggestions` / `data: ["…", "…", "…"]`).
   *
   * - [] in the initial state and whenever the backend emitted none —
   *   callers fall back to the client-side generateFollowUps() generator.
   * - Replaced per turn (cleared at the start of every send so a new
   *   question never shows the previous answer's suggestions).
   * - Cleared on thread switch (resetForThread) — suggestions are scoped
   *   to the conversation that produced them.
   */
  serverSuggestions: string[];
  /**
   * Conversation-level tool usage samples (frontend-rework Wave 2 — drives
   * the context rail's "Tools Used" section). One entry per COMPLETED tool
   * invocation across ALL turns in the active thread; unlike toolTrace this
   * survives subsequent sends and is cleared only on thread switch.
   */
  toolUsage: ToolUsageSample[];
  /** Trigger the slash-command branch or the SSE LLM call for `question`. */
  send: (question: string) => Promise<void>;
  /**
   * Resubmit the last question after a failure (Round 1 Foundation — Retry).
   *
   * WHY a dedicated method (not "page calls send(lastQuestion) itself"):
   * the failed user message is already in `localMessages` (we append it
   * optimistically BEFORE the request fires). A naive re-send would echo the
   * same user bubble twice. retry() re-uses the existing bubble: it resends
   * the question over the wire but skips the optimistic append when the last
   * log entry is already that exact user message. No-op when there is nothing
   * to retry or a stream is already in flight.
   */
  retry: () => Promise<void>;
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
  // `iterationEvent` — latest agent_iteration event (PLAN-0099 W4).
  // WHY state (not ref): the AgentIterationProgress component reads this via
  // props; React must re-render the strip whenever the stage/iteration/elapsed
  // values change. A ref would not trigger that re-render and the strip would
  // appear frozen — defeating the entire "no perceived hang" goal.
  const [iterationEvent, setIterationEvent] = useState<AgentIterationEvent | null>(null);
  // `toolTrace` — debug record of every tool invocation in the CURRENT/LAST
  // turn (args + result + latency). Survives stream completion on purpose:
  // the ?debug=1 ToolTraceDrawer is opened AFTER the answer settles. Reset at
  // the start of each send and on resetForThread.
  // WHY state (not ref): the drawer renders from it — React must re-render as
  // tool_call/tool_result events land so an open drawer updates live.
  const [toolTrace, setToolTrace] = useState<ToolTraceEntry[]>([]);
  // `verifying` — TRUE during the post-synthesis grounding-validation phase
  // (Phase-1 `status: verifying` event). Drives the Research timeline's
  // "Verifying answer against sources…" line. Reset per send + on stream end.
  const [verifying, setVerifying] = useState(false);
  // `serverSuggestions` — follow-up strings from the `suggestions` SSE event
  // (Wave-1 backend addition). Replaced per turn, cleared on thread switch.
  // WHY state (not ref): the page derives the chips row from it — React must
  // re-render when the suggestions land (they arrive AFTER the final token,
  // typically in the same flush as the `done` event).
  const [serverSuggestions, setServerSuggestions] = useState<string[]>([]);
  // `toolUsage` — conversation-level accumulator of completed tool calls
  // (tool name + latency). Feeds the context rail's "Tools Used" section.
  // Deliberately NOT cleared per send (unlike toolTrace) — the section
  // aggregates across the whole conversation; see resetForThread.
  const [toolUsage, setToolUsage] = useState<ToolUsageSample[]>([]);

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

  // `lastQuestionRef` — the most recent question that FAILED (used by retry()).
  // WHY a ref (not state): only read inside the retry() callback — no render
  // depends on it, so a state setter would just cause useless re-renders.
  // Set on every error exit path; cleared on successful completion so a
  // stale question can never be resubmitted after a later success.
  const lastQuestionRef = useRef<string | null>(null);

  // `toolStartRef` — performance.now() timestamp per tool name for the
  // in-flight turn, used to compute client-measured latency when the matching
  // tool_result event arrives. A ref because timestamps never drive a render.
  const toolStartRef = useRef<Map<string, number>>(new Map());

  // `currentIterationRef` — the latest `agent_iteration.iteration` seen this
  // turn, used to TAG each tool_call's trace entry with the loop step it ran
  // in (Phase-1 Research timeline grouping). A ref because tagging happens
  // inside the tool_call handler and must read the freshest iteration without
  // forcing a re-render or re-binding the send() closure. Reset to 0 per send.
  const currentIterationRef = useRef(0);

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
    // PLAN-0099 W4: clear the agent-iteration strip too — otherwise it would
    // remain visible after cancellation showing a stale "Reasoning over…"
    // label that no longer reflects reality.
    setIterationEvent(null);
    // Phase-1: clear the verify flag so the timeline doesn't show a stale
    // "Verifying…" line after a cancelled turn.
    setVerifying(false);
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
    // PLAN-0099 W4: agent-iteration progress is scoped to a single turn; a
    // thread switch must reset it so the new thread starts with a clean strip.
    setIterationEvent(null);
    // Round 1 Foundation: the debug trace + retry context are scoped to a
    // single thread's last turn — both must not leak across a thread switch
    // (the drawer would show another conversation's tools; retry would
    // resubmit a question into the wrong thread).
    setToolTrace([]);
    toolStartRef.current.clear();
    currentIterationRef.current = 0;
    setVerifying(false);
    lastQuestionRef.current = null;
    // Wave 2: suggestions + tool-usage stats are conversation-scoped — both
    // must reset on thread switch or the new thread's rail/chips would show
    // another conversation's tools and follow-ups.
    setServerSuggestions([]);
    setToolUsage([]);
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
    // WHY the optional `opts` param: retry() resends a question whose user
    // bubble is ALREADY in the log (appended optimistically by the failed
    // attempt). `skipUserEcho` suppresses the duplicate echo in that case.
    // Regular callers (page, EntityChatPanel) pass only the question — the
    // public `send: (question) => Promise<void>` contract is unchanged.
    async (rawInput: string, opts?: { skipUserEcho?: boolean }): Promise<void> => {
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

      // FR-5.3 (LOW-006): isStreamingRef.current = true is set HERE, before the
      // first setLocalMessages call, to close the race window between the React
      // re-render triggered by setStreaming and the ref update. Any concurrent
      // send() call that fires after setLocalMessages but before the ref was
      // previously set would see isStreamingRef.current === false and pass the
      // guard — dispatching a second overlapping stream. Setting the ref first
      // makes the guard race-free regardless of React batching semantics.
      isStreamingRef.current = true;

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
      setLocalMessages((prev) => {
        // Retry path: the failed attempt already appended this exact user
        // bubble — appending again would render the question twice. We only
        // skip when the LAST entry is a user message with identical content
        // (defensive: if the log changed in between, fall through and append).
        if (opts?.skipUserEcho) {
          // Round 4 hardening: scan BACKWARDS for the most recent user
          // message instead of only checking the last entry. WHY: an
          // interrupted stream now appends the PARTIAL assistant message to
          // the log before arming retry — so on retry the failed question is
          // no longer the last entry (the partial answer is). Looking only at
          // prev[len-1] would re-echo the question. Scanning past assistant
          // messages and slash turns to the latest user bubble restores the
          // "no duplicate echo" contract for every failure shape. The scan is
          // safe because skipUserEcho is only set by retry(), and retry()'s
          // lastQuestionRef was armed by the failure of EXACTLY this question
          // — the most recent user message is always that question's bubble.
          for (let i = prev.length - 1; i >= 0; i--) {
            const entry = prev[i];
            if ("kind" in entry) continue; // slash turn — keep scanning
            if (entry.role === "user") {
              if (entry.content === question) return prev;
              // Most recent user message differs (log changed in between) —
              // fall through and append defensively, as before.
              break;
            }
            // assistant message (e.g. an interrupted partial) — keep scanning
          }
        }
        return [...prev, userMessage];
      });
      setChatError(null);
      // Round 1 Foundation (orphaned-spinner fix): activeTools was previously
      // only cleared on the `done`/[DONE]/`error`-event/cancel paths. When a
      // stream ended via reader exhaustion (server closed early) or a thrown
      // fetch error, stale tool entries survived in state and FLASHED inside
      // the next turn's StreamingBubble before that turn's own tool events
      // arrived. Clearing here guarantees every turn starts with a clean
      // tool slate regardless of how the previous turn ended.
      setActiveTools([]);
      // The debug trace is per-turn: a new send replaces the previous turn's
      // trace (the drawer always shows the latest turn).
      setToolTrace([]);
      toolStartRef.current.clear();
      // Phase-1: reset the Research-timeline accumulators for the new turn so
      // step grouping starts at 0 and no stale "Verifying…" line leaks in.
      currentIterationRef.current = 0;
      setVerifying(false);
      // Wave 2: clear the previous turn's server suggestions the moment a new
      // question fires — chips must never suggest follow-ups to an answer the
      // user has already moved past. (toolUsage is NOT cleared here — it is
      // the conversation-level accumulator; see resetForThread.)
      setServerSuggestions([]);
      // PLAN-0099 W4: clear any previous iteration event from the prior turn
      // BEFORE the new request fires. Without this, the strip would briefly
      // show the previous turn's stage (e.g. "Writing answer…") until the
      // first agent_iteration event of the new turn arrives.
      setIterationEvent(null);

      const controller = new AbortController();
      abortRef.current = controller;
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
        // ── Endpoint + body selection (tab-local wiring fix, intelligence tab) ──
        // BUG (2026-06-15, intelligence-tab chat): the entity branch previously
        // posted `{ message }` to the SYNC `/api/v1/chat/entity-context`
        // endpoint. That was broken on BOTH axes and produced a hard
        // 400 "question cannot be empty" for every entity (NVDA/TSLA included —
        // it was NOT the known AAPL market-data gap):
        //   1. WRONG FIELD: S8's EntityContextChatRequest (and S9's pre-proxy
        //      validation) require `question`, NOT `message`. The main chat
        //      schema uses `message`; the entity-context schema diverges and
        //      uses `question`. Sending `message` → S9 sees an empty `question`
        //      → 400 before the request ever reaches S8.
        //   2. WRONG ENDPOINT: `/api/v1/chat/entity-context` is the SYNC JSON
        //      endpoint (returns one `{answer: ...}` blob). This hook parses an
        //      SSE event stream, so even a 200 would never render. The SSE
        //      sibling is `/api/v1/chat/entity-context/stream`, which emits the
        //      identical event frames (status/thinking/tool_call/tool_result/
        //      token/done) the main `/chat/stream` path already parses below —
        //      verified live: NVDA streams token-by-token through this path.
        // The MAIN chat path (`entityId` unset) is untouched: same `/chat/stream`
        // endpoint, same `message` field the sibling verified working.
        const chatEndpoint = entityId
          ? "/api/v1/chat/entity-context/stream"
          : "/api/v1/chat/stream";
        // WHY the field name is endpoint-dependent: the two backend schemas use
        // different field names by design (main=`message`, entity-context=
        // `question`). We name the field to match the endpoint we're hitting.
        const chatBody: Record<string, unknown> = entityId
          ? { question, thread_id: threadId, entity_id: entityId }
          : { message: question, thread_id: threadId };

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
        // Wave 2: end-of-stream `metadata` fields (intent/provider/model/
        // latency_ms) — attached to the finalized assistant message so the
        // per-message meta strip can render them WITHOUT waiting for the
        // thread refetch (the server persists the same fields; this just
        // closes the gap for the optimistic local message).
        let pendingMeta: AssistantTurnMeta | null = null;
        // Wave 3 (false-interrupt fix): TRUE once a post-answer terminal event
        // (`suggestions` or `metadata`) has been observed. Both are emitted by
        // S8 strictly AFTER the complete answer (verified live: token… →
        // citations → suggestions → metadata → done). If the reader then
        // exhausts WITHOUT the final `done` frame (e.g. the connection closes
        // right after metadata, or the done frame is lost in the last network
        // chunk), the answer still COMPLETED — the interruption detector must
        // finalize cleanly instead of slapping a false "Response interrupted"
        // banner under a fully-delivered answer (the user-reported bug).
        let sawAnswerComplete = false;
        // Wave 3: text from the `final_answer` SSE event. S8 emits the full
        // answer as ONE final_answer frame in addition to the token frames.
        // Normally tokens win (finalContent is non-empty), but some backend
        // paths (cache hits, guardrail responses) emit NO token frames at all
        // — previously those settled as an EMPTY optimistic message and the
        // answer only appeared after a thread refetch. final_answer is the
        // fallback content source for exactly that shape.
        let finalAnswerText = "";

        // Helper: finalise a CLEAN stream end (done event / [DONE] sentinel)
        // and promote the bubble to a message. Interrupted ends (reader
        // exhaustion without done) take the dedicated path after the read
        // loop below — Round 4 hardening split the two so an interruption can
        // never masquerade as a complete answer.
        const finalize = () => {
          setStreaming(null);
          // Wave 3: tokens are the primary content source; final_answer is
          // the fallback for zero-token streams (see finalAnswerText above).
          const content = finalContent || finalAnswerText;
          if (content || pendingCitations.length > 0) {
            // Wave 2: MessageWithMeta — spread the metadata-event fields onto
            // the optimistic message so MessageBubble's meta strip shows
            // intent/provider/latency immediately (the server-persisted copy
            // carries the same fields when the thread is later refetched).
            const assistantMessage: MessageWithMeta = {
              message_id: crypto.randomUUID(),
              thread_id: threadId,
              role: "assistant",
              content,
              created_at: new Date().toISOString(),
              citations: pendingCitations,
              ...(pendingMeta ?? {}),
            };
            setLocalMessages((prev) => [...prev, assistantMessage]);
          }
          // Round 1 Foundation: a finalized stream is not a failure — clear
          // the retry context so a stale question can't be resubmitted later
          // from the error banner of an unrelated failure.
          lastQuestionRef.current = null;
          refetchThreads();
        };

        // ── Per-line demultiplexer ────────────────────────────────────────
        // Wave 3 (false-interrupt fix): the demux used to live inline in the
        // read loop, which made it impossible to re-run on the LEFTOVER
        // buffer after the reader exhausted. If the final network chunk
        // arrived without a trailing newline (arbitrary chunk boundaries are
        // legal — proxies re-frame freely), the closing `done` frame sat
        // unprocessed in `buffer` and the interruption detector fired under
        // a fully-delivered answer. Extracting the demux into a closure lets
        // the read loop AND the post-loop tail flush share one code path.
        //
        // Return contract (the closure cannot `return` out of send() itself):
        //   "ok"        — line consumed, keep reading
        //   "finalized" — clean end-of-stream handled (done/[DONE]); caller
        //                 must stop reading and exit send()
        //   "errored"   — server-emitted error handled; caller must exit
        const handleLine = (line: string): "ok" | "finalized" | "errored" => {
          // FR-5.6 (MED-013): use parseSSELine for field extraction — single
          // canonical parser (lib/sse-parser.ts) instead of inline slicing.
          // The stateful pendingEventName accumulation stays here because it
          // is tightly coupled to the streaming state machine.
          const parsed = parseSSELine(line);
          if (!parsed) return "ok";

          // event: line — update pending event name and move to next line.
          if (parsed.type !== "message") {
            pendingEventName = parsed.type;
            return "ok";
          }

          // data: line — extract payload and consume the pending event name.
          const payload = parsed.data;

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
            // PLAN-0099 W4: clear the iteration strip on clean stream end.
            // The streaming bubble is being promoted to a final MessageBubble;
            // the progress strip MUST disappear at the same time or it would
            // hover next to a settled answer (misleading "still working" cue).
            setIterationEvent(null);
            // Phase-1: the verify phase (if any) is over once `done` lands.
            setVerifying(false);
            finalize();
            return "finalized";
          }

          // Legacy [DONE] sentinel — backward compat with older backends.
          if (payload === "[DONE]") {
            // WHY clear here too: same reason as the `done` event handler above.
            // Both end-of-stream paths must reset tool indicators.
            setActiveTools([]);
            // PLAN-0099 W4: same reasoning — clear the iteration strip on
            // legacy [DONE] sentinel so both end-of-stream paths agree.
            setIterationEvent(null);
            setVerifying(false);
            finalize();
            return "finalized";
          }

          try {
            const data = JSON.parse(payload) as Record<string, unknown>;

            // ── Tool-use events (PLAN-0067 W11-5) ────────────────────────
            // These three event types are emitted by SSEEmitter during the
            // tool-use phase (before any token chunks arrive). They drive
            // ToolCallIndicator in the streaming bubble.

            if (eventName === "agent_iteration") {
              // PLAN-0099 W4: agent loop transition event. Fired by S8 at
              // every loop boundary (planning → reasoning → synthesis) so
              // the frontend can render a progress strip that NEVER goes
              // blank between tool batches.
              //
              // Wire shape (frozen with Agent A's backend contract):
              //   { iteration: number, max_iterations: number,
              //     stage: "planning_tools"|"reasoning_over_results"|"synthesizing",
              //     tools_completed_total: number, elapsed_ms: number }
              //
              // WHY a minimal type-narrowing block (not zod): the wire schema
              // is owned by S8 and exercised by integration tests there. A
              // shape mismatch here surfaces as a missing strip (graceful
              // degradation) rather than a thrown error — we deliberately do
              // not bring down the entire stream over a malformed iter event.
              const ie = data as {
                iteration?: number;
                max_iterations?: number;
                stage?: AgentIterationEvent["stage"];
                tools_completed_total?: number;
                elapsed_ms?: number;
              };
              if (
                typeof ie.iteration === "number" &&
                typeof ie.max_iterations === "number" &&
                (ie.stage === "planning_tools" ||
                  ie.stage === "reasoning_over_results" ||
                  ie.stage === "synthesizing") &&
                typeof ie.tools_completed_total === "number" &&
                typeof ie.elapsed_ms === "number"
              ) {
                setIterationEvent({
                  iteration: ie.iteration,
                  max_iterations: ie.max_iterations,
                  stage: ie.stage,
                  tools_completed_total: ie.tools_completed_total,
                  elapsed_ms: ie.elapsed_ms,
                });
                // Phase-1: remember the current loop step so the NEXT tool_call
                // gets tagged with it for the Research timeline's step grouping.
                currentIterationRef.current = ie.iteration;
              }
            } else if (eventName === "thinking") {
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
              const tc = data as {
                tool?: string;
                label?: string;
                status?: string;
                input?: Record<string, unknown>;
              };
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
                    // Wave 3 (40s-wait feedback): wall-clock receipt time so
                    // ToolCallIndicator can render a live "Ns" elapsed chip
                    // next to each running tool. Date.now (not performance.now)
                    // because the indicator compares against Date.now() in a
                    // 1s ticker — and fake-timer tests can control both.
                    startedAt: Date.now(),
                  },
                ]);
                // Round 1 Foundation: record the debug trace entry + the
                // wall-clock start so the matching tool_result can compute a
                // client-side latency. Same idempotency rule as activeTools.
                toolStartRef.current.set(tc.tool, performance.now());
                setToolTrace((prev) => [
                  ...prev.filter((t) => t.tool !== tc.tool),
                  {
                    tool: tc.tool as string,
                    label: tc.label as string,
                    // `input` carries the JSON arguments the LLM passed to the
                    // tool (S8 SSEEmitter W11-3 shape). Default to {} so the
                    // drawer can always JSON.stringify without null checks.
                    args: tc.input ?? {},
                    status: "running",
                    result: null,
                    latencyMs: null,
                    latencySource: null,
                    // Phase-1: tag with the current loop step + seed the
                    // result label with the call-time label (the tool_result
                    // event refines it with the input-aware version).
                    iteration: currentIterationRef.current,
                    resultLabel: tc.label as string,
                  },
                ]);
              }
            } else if (eventName === "tool_result") {
              // `tool_result` — a tool has completed. The data shape from S8:
              //   { type: "tool_result", tool: string, status: "ok"|"empty"|"error", item_count: number }
              // We map the status onto the existing ToolCallState entry.
              const tr = data as { tool?: string; status?: string; label?: string };
              if (tr.tool && tr.status) {
                const resultStatus = (tr.status as ToolCallState["status"]) ?? "error";
                // Phase-1: the tool_result carries the input-aware human label
                // (e.g. "Searching news for NVIDIA") — capture it so the
                // Research timeline shows the specific subject on completion.
                const resultLabel =
                  typeof tr.label === "string" && tr.label.length > 0 ? tr.label : null;
                setActiveTools((prev) =>
                  prev.map((t) =>
                    t.name === tr.tool
                      ? { ...t, status: resultStatus }
                      : t,
                  ),
                );
                // Round 1 Foundation: close out the trace entry.
                // Latency: prefer the server-emitted duration_ms (Wave-1
                // backend addition — server-measured, authoritative), else
                // client wall-clock from the tool_call receipt timestamp.
                const startedAt = toolStartRef.current.get(tr.tool);
                const serverDuration =
                  typeof (data as { duration_ms?: unknown }).duration_ms === "number"
                    ? ((data as { duration_ms: number }).duration_ms)
                    : null;
                const latencyMs =
                  serverDuration ??
                  (startedAt !== undefined
                    ? Math.round(performance.now() - startedAt)
                    : null);
                // Wave 2: record WHERE the number came from so the drawer
                // can drop the "client-measured" qualifier for server truth.
                const latencySource: ToolTraceEntry["latencySource"] =
                  serverDuration !== null
                    ? "server"
                    : latencyMs !== null
                      ? "client"
                      : null;
                // Keep everything except the demux keys as the raw result
                // payload (today: item_count; future fields flow through
                // automatically — forward-compatible by construction).
                const resultPayload: Record<string, unknown> = {};
                for (const [k, v] of Object.entries(data)) {
                  if (k !== "type" && k !== "tool" && k !== "status") {
                    resultPayload[k] = v;
                  }
                }
                setToolTrace((prev) =>
                  prev.map((t) =>
                    t.tool === tr.tool
                      ? {
                          ...t,
                          status: resultStatus,
                          result: resultPayload,
                          latencyMs,
                          latencySource,
                          // Phase-1: prefer the result event's input-aware
                          // label; fall back to the call-time one already set.
                          resultLabel: resultLabel ?? t.resultLabel,
                        }
                      : t,
                  ),
                );
                // Wave 2: conversation-level accumulation for the rail's
                // "Tools Used" section. Append-only (one sample per
                // completed invocation) so count + average latency can be
                // derived; cleared only on thread switch.
                setToolUsage((prev) => [
                  ...prev,
                  { tool: tr.tool as string, latencyMs },
                ]);
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
                pendingCitations = data
                  .filter(
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
                  )
                  // QA Wave-3 closeout: the SSE wire shape is the canonical
                  // rag-chat citation ({ref, id, source_name, confidence, …});
                  // map onto the legacy contract (article_id/source/
                  // relevance_score) so CitationList/CitationBar never touch
                  // an undefined `source` (toLowerCase crash, see import note).
                  .map(
                    (c) =>
                      normalizeCitation(c) as NonNullable<
                        Message["citations"]
                      >[number],
                  );
              }
            } else if (eventName === "suggestions") {
              // Wave 2 (Wave-1 backend): server-generated follow-up
              // suggestions, emitted AFTER the final token. Wire shape is a
              // bare JSON string array (verified live):
              //   event: suggestions
              //   data: ["What's the latest news on Apple Inc.?", …]
              // WHY filter to non-empty strings: defensive — a malformed
              // entry must degrade to "one fewer chip", never to a chip
              // rendering "undefined". The page PREFERS these over the
              // client-templated generateFollowUps() output and falls back
              // when this array is empty.
              if (Array.isArray(data)) {
                setServerSuggestions(
                  data.filter(
                    (s): s is string =>
                      typeof s === "string" && s.trim().length > 0,
                  ),
                );
              }
              // Wave 3 (false-interrupt fix): suggestions are only ever
              // emitted AFTER the full answer — seeing one proves the answer
              // completed even if the trailing done frame never arrives.
              sawAnswerComplete = true;
            } else if (eventName === "metadata") {
              // Wave 2: end-of-stream turn metadata — captured into
              // pendingMeta so finalize() can attach it to the optimistic
              // assistant message (the per-message meta strip renders
              // intent/provider/model/latency from these fields).
              // Type-narrow each field individually: a missing/odd-typed
              // field degrades to "fragment absent" in the strip, never to
              // a thrown error that would kill the stream.
              const md = data as Record<string, unknown>;
              pendingMeta = {
                intent: typeof md.intent === "string" ? md.intent : null,
                provider:
                  typeof md.provider === "string" ? md.provider : null,
                model: typeof md.model === "string" ? md.model : null,
                latency_ms:
                  typeof md.latency_ms === "number" ? md.latency_ms : null,
              };
              // Wave 3 (false-interrupt fix): metadata is the LAST data-bearing
              // event before done (verified live). Its arrival proves the
              // answer completed — see sawAnswerComplete declaration.
              sawAnswerComplete = true;
            } else if (eventName === "final_answer") {
              // Wave 3: S8 emits the complete answer as one final_answer frame
              // alongside (after) the token frames. Captured as the FALLBACK
              // content source for streams that emitted no token frames at all
              // (cache hits, guardrail responses) — finalize() prefers the
              // token-accumulated finalContent when it is non-empty, so this
              // never overrides genuinely streamed text.
              const fa = data as { text?: unknown };
              if (typeof fa.text === "string") {
                finalAnswerText = fa.text;
              }
            } else if (eventName === "error") {
              const msg =
                typeof data.message === "string"
                  ? data.message
                  : "Stream error from server";
              setChatError(msg);
              setStreaming(null);
              // PLAN-0099 W4: clear progress strip on server-emitted error
              // so we don't leave a stale "Reasoning over…" strip hovering
              // above the error banner.
              setIterationEvent(null);
              setVerifying(false);
              setActiveTools([]);
              // Round 1 Foundation: remember the question so the error
              // banner's Retry button can resubmit it.
              lastQuestionRef.current = question;
              return "errored";
            } else if (eventName === "status") {
              // Phase-1: the `status` event carries a coarse pipeline-phase
              // `step` token. We only act on "verifying" — the post-synthesis
              // grounding-validation phase that used to be silent. Setting the
              // flag drives the Research timeline's "Verifying answer against
              // sources…" line. All other steps (cache_hit, loading_context,
              // entity_resolution) are accepted silently — the timeline/tool
              // chrome already covers them.
              const st = data as { step?: unknown };
              if (st.step === "verifying") {
                setVerifying(true);
              }
            }
            // contradictions — no UI action needed yet; accepted
            // silently so the parser never throws on them.
          } catch {
            // Non-JSON line — keep-alive comment, blank line, etc. Skip.
          }
          return "ok";
        };

        // Read loop: SSE frames are newline-delimited; we split on \n,
        // keep the trailing partial in `buffer` for the next pump.
        // Each SSE event may have an `event:` field before its `data:` line.
        // handleLine demultiplexes token/citations/done/error events.
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const outcome = handleLine(line);
            // "finalized" / "errored" already performed all state updates —
            // exit send() entirely (the finally block releases the reader).
            if (outcome !== "ok") return;
          }
        }

        // ── Reader exhausted: flush the tail BEFORE judging the stream ────
        // Wave 3 (false-interrupt fix, part 1): network chunk boundaries are
        // arbitrary — the final chunk can end WITHOUT a trailing newline, in
        // which case the closing `done` frame (or the metadata/suggestions
        // events before it) is still sitting in `buffer` and/or inside the
        // TextDecoder's internal state. Flush both and run the leftover lines
        // through the same demux. Once the stream is closed, a final line
        // without a trailing \n IS a complete line — process it too.
        buffer += decoder.decode(); // flush any buffered multi-byte sequence
        if (buffer.length > 0) {
          for (const line of buffer.split("\n")) {
            const outcome = handleLine(line);
            if (outcome !== "ok") return; // late done/error handled cleanly
          }
        }

        // ── Wave 3 (false-interrupt fix, part 2): terminal-event fallback ──
        // The done frame genuinely never arrived — but if a post-answer
        // terminal event (suggestions / metadata) did, the answer COMPLETED;
        // only the closing frame was lost (observed live: the stream can end
        // right after `metadata` when a proxy closes the connection eagerly).
        // Finalizing cleanly here is what guarantees the detector NEVER
        // shows "Response interrupted" under a fully-delivered answer.
        if (sawAnswerComplete) {
          setActiveTools([]);
          setIterationEvent(null);
          setVerifying(false);
          finalize();
          return;
        }

        // ── Reader exhausted WITHOUT done AND without terminal events ─────
        // The server (or a proxy / the network path) closed the stream early
        // — a mid-response network blip, an S8 worker crash, an LB idle
        // timeout. Round 1 made sure this path cleared the spinners; Round 4
        // makes the interruption VISIBLE instead of silently presenting the
        // truncated text as a complete answer:
        //
        //   1. Partial content is preserved VERBATIM as its own assistant
        //      message (nothing the user already read is thrown away, and no
        //      synthetic "[Response interrupted]" text is spliced into the
        //      model's words — pre-Round-4 behaviour).
        //   2. chatError carries an explicit interruption notice — the page
        //      renders it as the inline role="alert" banner directly under
        //      the partial message, WITH the Retry button.
        //   3. lastQuestionRef is armed so Retry resends the question without
        //      re-echoing the user bubble (see the skipUserEcho backward scan).
        setStreaming(null);
        // Same chrome-reset trio as every other end-of-stream path: spinners
        // and the iteration strip must never hover next to the error banner.
        setActiveTools([]);
        setIterationEvent(null);
        setVerifying(false);
        if (finalContent || pendingCitations.length > 0) {
          const partialMessage: Message = {
            message_id: crypto.randomUUID(),
            thread_id: threadId,
            role: "assistant",
            content: finalContent,
            created_at: new Date().toISOString(),
            citations: pendingCitations,
          };
          setLocalMessages((prev) => [...prev, partialMessage]);
        }
        lastQuestionRef.current = question;
        // Distinct copy for the two shapes: "you saw part of the answer" vs
        // "nothing arrived at all" — the recovery action (Retry) is the same.
        setChatError(
          finalContent
            ? "Response interrupted — the connection dropped mid-answer. The partial response is shown above."
            : "Response interrupted before any content arrived. Check your connection and retry.",
        );
        // Still refetch: the server may have persisted the user message (and
        // created the thread) before the stream died — the sidebar should
        // reflect whatever made it through.
        refetchThreads();
      } catch (err) {
        // AbortError is the EXPECTED outcome of cancel() / unmount — it is
        // not an error condition, so we swallow it and only clear the
        // streaming bubble.
        if (err instanceof Error && err.name === "AbortError") {
          setStreaming(null);
          // PLAN-0099 W4: abort path must also clear the iteration strip; cancel()
          // already does this for user-initiated aborts, but unmount/race paths
          // also land here. Belt-and-braces clearing avoids a leaked strip.
          setIterationEvent(null);
          setVerifying(false);
          return;
        }
        setStreaming(null);
        // PLAN-0099 W4: clear strip on the error fallback path too.
        setIterationEvent(null);
        setVerifying(false);
        // Round 1 Foundation: thrown-error path (network failure, non-2xx,
        // null body) — clear any tool spinners that were mid-flight and arm
        // the Retry button with the failed question.
        setActiveTools([]);
        lastQuestionRef.current = question;
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

  /**
   * `retry` — resubmit the last FAILED question (Round 1 Foundation).
   *
   * Guards: no-op when there is no failed question (lastQuestionRef is only
   * set on error exit paths and cleared on success/thread-switch) or while a
   * stream is in flight. Clears the error banner eagerly so the user sees the
   * retry start immediately, then delegates to send() with skipUserEcho —
   * the failed user bubble is already in the log.
   */
  const retry = useCallback(async (): Promise<void> => {
    const question = lastQuestionRef.current;
    if (!question || isStreamingRef.current) return;
    setChatError(null);
    await send(question, { skipUserEcho: true });
  }, [send]);

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
    // PLAN-0082 Wave B: pending write-action confirmation (create_alert, etc.).
    // The chat page reads this to render ActionConfirmModal when non-null.
    pendingAction,
    clearPendingAction,
    // PLAN-0099 W4: latest agent_iteration event for the AgentIterationProgress strip.
    iterationEvent,
    // Round 1 Foundation: debug tool trace (args/result/latency) for ToolTraceDrawer.
    toolTrace,
    // Phase-1: verify-phase flag for the Research timeline's "Verifying…" line.
    verifying,
    // Wave 2: server follow-up suggestions (preferred over the client
    // generator) + conversation-level tool usage for the rail.
    serverSuggestions,
    toolUsage,
    send,
    // Round 1 Foundation: resubmit the last failed question (error-banner Retry).
    retry,
    cancel,
    resetForThread,
  };
}
