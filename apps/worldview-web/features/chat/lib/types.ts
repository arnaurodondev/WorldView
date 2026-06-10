/**
 * features/chat/lib/types.ts — Local chat-page types shared by the page
 * orchestrator and the extracted sub-components.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): the SlashTurn / LogEntry / StreamingMessage
 * types were inline in `app/(app)/chat/page.tsx`. Moving them here lets the
 * sub-components (MessageBubble, SlashTurnBlock, StreamingBubble, ThreadItem)
 * import the shapes without circular file dependencies.
 */

import type { Message } from "@/types/api";
import type { ParsedCommand } from "@/lib/chat/slash-commands";

/**
 * StreamingMessage — transient in-flight bubble displayed while SSE tokens
 * arrive. Once the stream completes (either [DONE] sentinel or reader
 * exhaustion), the accumulated text becomes a proper Message in the
 * messages array.
 */
export interface StreamingMessage {
  /** Tokens accumulated so far from the SSE stream. */
  text: string;
  /** Whether the stream is still open (controls blinking cursor visibility). */
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
export interface SlashTurn {
  kind: "slash";
  message_id: string;
  command: ParsedCommand;
  /** Echo of the user's typed input, shown as a user bubble above the card. */
  input: string;
  created_at: string;
}

/** Either a regular Message or a slash-command turn — what the log iterates over. */
export type LogEntry = Message | SlashTurn;

/**
 * PendingActionEvent — received from the ``pending_action`` SSE event emitted
 * by S8 when the LLM invokes a write-action tool (e.g. ``create_alert``).
 *
 * WHY A SEPARATE TYPE (not part of StreamingMessage):
 * The ``pending_action`` event is a *blocking* event — the frontend must
 * show a confirmation modal and wait for user input before the pipeline
 * continues.  It is not a transient token or informational spinner.
 * Giving it a first-class type makes it easy to pass around without
 * casting or duck-typing at the call site.
 *
 * The ``params`` dict mirrors the ``params`` field from the SSE data
 * (entity_id, condition, threshold, severity).  The frontend sends these
 * back in the request body of POST /api/v1/chat/proposals/{id}/confirm.
 */
/**
 * AgentIterationEvent — received from the ``agent_iteration`` SSE event emitted
 * by S8 (rag-chat) at every transition of the tool-calling loop.
 *
 * WHY THIS EXISTS (PLAN-0099 W4 UX fix):
 * Today the chat appears to "hang" between tool batches. The flow for a slow
 * research query looks like:
 *   0-8s    tool spinners visible (good)
 *   8-16s   SILENT — LLM is reasoning over iter-1 results (looks broken)
 *   16-24s  SILENT — LLM is reasoning over iter-2 results (looks broken)
 *   24-30s  synthesis stream begins
 * The new `agent_iteration` event fills those silent gaps with an
 * always-visible progress strip ("Step 2 of 8 · Reasoning over 4 results…").
 *
 * WHY 3 STAGES (not free-text):
 * A bounded enum lets the frontend pick a stable icon + copy for each phase
 * without parsing backend strings. Adding a 4th stage requires a coordinated
 * BE/FE change — desirable: it forces us to think about the UX of the new
 * transition.
 *
 * EMIT TIMING (per Agent A's backend contract):
 *   - BEFORE iter 0's LLM call → stage="planning_tools", iteration=0
 *   - BEFORE iter N>0's LLM call → stage="reasoning_over_results", iteration=N
 *   - BEFORE the synthesis streaming call → stage="synthesizing"
 */
export interface AgentIterationEvent {
  /** 0-indexed iteration number within the tool loop. */
  iteration: number;
  /** Loop budget ceiling — drives the "Step N of M" copy. */
  max_iterations: number;
  /** Bounded stage enum; component switches icon + label on this. */
  stage: "planning_tools" | "reasoning_over_results" | "synthesizing";
  /** Running cumulative count of tools completed so far in this turn. */
  tools_completed_total: number;
  /** Wall-clock milliseconds since the loop started — drives the elapsed chip. */
  elapsed_ms: number;
}

/**
 * ToolTraceEntry — one tool invocation captured for the debug ToolTraceDrawer
 * (PRD-0089 Q-8, completed in Round 1 Foundation).
 *
 * WHY A SEPARATE TYPE FROM ToolCallState:
 * ToolCallState is the *user-facing* progress view-model (label + status) shown
 * in the streaming bubble and cleared the moment the stream ends. The trace is
 * the *debug* record: it keeps the raw tool name, the JSON arguments the LLM
 * passed, the raw result metadata, and a latency measurement — and it survives
 * past the end of the stream so an engineer can open the drawer AFTER the
 * answer settles and inspect what happened.
 *
 * LATENCY IS CLIENT-MEASURED: the SSE `tool_result` event does not carry a
 * server-side duration today (backend gap — S8 SSEEmitter would need a
 * `duration_ms` field). We approximate by timestamping the `tool_call` event
 * receipt and the matching `tool_result` receipt with `performance.now()`.
 * This includes network jitter but is accurate enough for "which tool was
 * slow" debugging. If S8 ever emits `duration_ms` we prefer it (see
 * useChatStream's tool_result handler).
 */
export interface ToolTraceEntry {
  /** Internal tool name from the SSE event, e.g. "search_documents". */
  tool: string;
  /** User-friendly label, e.g. "Searching documents..." */
  label: string;
  /** JSON arguments the LLM passed to the tool (from the tool_call event). */
  args: Record<string, unknown>;
  /** Terminal status once tool_result arrives; "running" until then. */
  status: "running" | "ok" | "empty" | "error";
  /**
   * Raw result metadata from the tool_result event (item_count, error info,
   * any future fields) — everything except the demux keys (type/tool/status).
   * Null until the tool_result event arrives.
   */
  result: Record<string, unknown> | null;
  /**
   * Client-measured wall-clock latency in ms (tool_call → tool_result).
   * Null while the tool is still running. Prefer the server-side
   * `duration_ms` when the backend emits one (currently it does not).
   */
  latencyMs: number | null;
}

export interface PendingActionEvent {
  /** Server-generated UUID — sent back as the path param on confirm. */
  proposal_id: string;
  /** Internal tool name, e.g. "create_alert". */
  tool: string;
  /** Human-readable description of the pending action shown in the modal. */
  description: string;
  /**
   * Safe action parameters (never contains user_id or tenant_id).
   * Passed to the confirm endpoint in the request body.
   */
  params: {
    entity_id?: string;
    condition?: string;
    threshold?: Record<string, unknown>;
    severity?: string;
    [key: string]: unknown;
  };
}
