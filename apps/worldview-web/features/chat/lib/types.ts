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
  // ── PLAN-0089 K Block A T-03 — Q-9 metadata fields ────────────────────────
  // WHY optional + on StreamingMessage: the `metadata` SSE event arrives
  // before the answer is finalised; we accumulate provider/model/latency on
  // the streaming bubble and copy them onto the persisted Message in
  // finalize() so the side rail can show "served by deepinfra/deepseek-r1
  // in 1.2s" without an extra round-trip.
  intent?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
  message_id?: string;
  /** Contradictions accumulated during this turn (Q-9 side-channel). */
  contradictions?: Array<Record<string, unknown>>;
  /**
   * PLAN-0100 W2 T-W2-03 — aggregate pre-tool status badge.
   *
   * Emitted by ``chat_orchestrator`` ONCE per turn, right after iteration-0
   * decides which tools to call. Carries human-readable summary text such
   * as ``"Loading get_price_history, search_news… (2 more)…"`` so the
   * streaming bubble can show user-visible feedback within ~1-3s — long
   * before the synthesised answer's first token arrives.
   *
   * Cleared (undefined) on every new ``send()`` call. The badge renders
   * ABOVE the ``ToolCallTray`` pills; both can be visible at the same time.
   */
  initial_status?: string;
  /**
   * PLAN-0103 W21 (BP-642) — set to ``true`` once the backend's
   * ``final_answer`` SSE event has rewritten ``text`` with a post-grounding
   * (numeric-corrected) version. The UI uses this flag to render a small
   * "✓ grounded" badge so the user understands the answer they're reading
   * was refined post-stream (rather than glitching mid-answer).
   */
  grounded?: boolean;
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
