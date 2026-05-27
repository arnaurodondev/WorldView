/**
 * features/chat/components/MessageTurn.tsx — stub placeholder.
 *
 * Full implementation lands in T-07. This stub exists only so T-06 type-
 * checks at commit time; the type signature is the same as the T-07 final
 * to avoid touching call-sites between commits.
 */

"use client";

import type { Message } from "@/types/api";
import type { ToolCallState } from "@/features/chat/components/ToolCallIndicator";

interface MessageTurnProps {
  readonly turn: Message;
  readonly isStreaming?: boolean;
  readonly size?: "default" | "compact";
  readonly onFollowUp?: (suggestion: string) => void;
  readonly activeTools?: ToolCallState[];
  /**
   * Optional intent label (e.g. "REASONING"). Not on `Message` because the
   * backend Q-9 wire shape did not finalise it as a persisted field; the
   * page passes it only for the streaming turn from `StreamingMessage`.
   */
  readonly intent?: string | null;
}

export function MessageTurn(_props: MessageTurnProps) {
  // T-07 will replace this entirely. Intentional no-op so the type
  // surface is real but the visual layer is the legacy bubble.
  return null;
}
