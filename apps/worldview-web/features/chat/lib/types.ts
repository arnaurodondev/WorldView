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
 * LATENCY SOURCE (frontend-rework Wave 2): the SSE `tool_result` event now
 * carries a SERVER-MEASURED `duration_ms` (Wave-1 backend change) — when
 * present it is the authoritative latency and `latencySource` is "server".
 * For older backends (or a missing field) we fall back to the client
 * wall-clock approximation (tool_call receipt → tool_result receipt via
 * `performance.now()`, includes network jitter) and mark it "client" so the
 * drawer can qualify the number (`~123 ms`) instead of presenting an
 * estimate as truth.
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
   * Tool latency in ms. Server-measured (`duration_ms` from the tool_result
   * event) when available, else client wall-clock (tool_call → tool_result).
   * Null while the tool is still running. See `latencySource` for which.
   */
  latencyMs: number | null;
  /**
   * Where `latencyMs` came from — "server" (authoritative `duration_ms`
   * from S8) or "client" (wall-clock approximation incl. network jitter).
   * Null while the tool is still running. The ToolTraceDrawer prefixes
   * client-measured values with "~" and drops the qualifier for server ones.
   */
  latencySource: "server" | "client" | null;
  /**
   * Phase-1 Research timeline: the 0-indexed agent-loop iteration this tool was
   * called in (the latest `agent_iteration.iteration` seen when the `tool_call`
   * arrived). Lets the timeline group steps under "Step 1 / Step 2" headers.
   * 0 when no agent_iteration event has been seen yet (single-iteration or
   * classical answers) — they all fold into one implicit step.
   */
  iteration: number;
  /**
   * Phase-1 Research timeline: the input-aware human label from the
   * `tool_result` SSE event (e.g. "Searching news for NVIDIA"). Falls back to
   * the `tool_call` label when the result omits it (older backends). This is
   * what the timeline renders; `label` (the call-time label) is kept for the
   * debug drawer's verbatim record.
   */
  resultLabel: string | null;
}

/**
 * ResultPreviewItem — one item from the `result_preview` array on a
 * tool_result SSE event (Wave-1 backend addition).
 *
 * WHY {id, title}: the preview answers "WHAT did this tool actually return?"
 * at a glance — titles are the human-meaningful part; ids let an engineer
 * correlate with backend logs. The full payload never travels over SSE
 * (could be megabytes for a screener call); the preview is the curated
 * top-N summary S8 considers representative.
 */
export interface ResultPreviewItem {
  id: string;
  title: string;
}

/**
 * ToolUsageSample — one completed tool invocation, accumulated across the
 * WHOLE conversation (unlike ToolTraceEntry, which is per-turn).
 *
 * WHY A SEPARATE ACCUMULATOR (frontend-rework Wave 2 — context-rail "Tools
 * Used" section): toolTrace is deliberately reset at the start of every send
 * so the ?debug=1 drawer always shows the LATEST turn. The rail's Tools Used
 * section answers a different question — "which platform tools produced the
 * answers in this conversation, how often, and how fast on average" — which
 * requires samples to survive across turns. Cleared only on thread switch
 * (resetForThread), mirroring how localMessages is scoped.
 */
export interface ToolUsageSample {
  /** Internal tool name from the SSE event, e.g. "get_entity_narrative". */
  tool: string;
  /** Server-measured duration_ms when emitted; client wall-clock fallback; null when neither was available. */
  latencyMs: number | null;
}

/**
 * AssistantTurnMeta — end-of-stream `metadata` SSE fields attached to the
 * finalized assistant message (frontend-rework Wave 2 — message meta strip).
 *
 * WHY AN INTERSECTION TYPE (not editing types/api.ts Message): the server's
 * ThreadDetailResponse already returns intent/provider/model/latency_ms per
 * message — the canonical Message type just never declared them. Declaring
 * the optional extension HERE (chat-owned file) lets the meta strip read the
 * fields from both historical messages (server-supplied) and just-streamed
 * ones (captured from the `metadata` SSE event) without touching the shared
 * types/api.ts surface owned by another workstream.
 */
export interface AssistantTurnMeta {
  intent?: string | null;
  provider?: string | null;
  model?: string | null;
  latency_ms?: number | null;
}

/** Message possibly carrying the assistant-turn metadata extension. */
export type MessageWithMeta = Message & AssistantTurnMeta;

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
