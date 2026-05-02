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
