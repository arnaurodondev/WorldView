/**
 * features/chat/components/MessageMetaStrip.tsx — stub placeholder.
 * Full implementation lands in T-09. Type surface is the final shape;
 * body is intentionally a no-op so MessageTurn typechecks at T-07.
 */

"use client";

interface MessageMetaStripProps {
  readonly role: "user" | "assistant";
  readonly intent?: string | null;
  readonly provider?: string | null;
  readonly model?: string | null;
  readonly latencyMs?: number | null;
  readonly createdAt?: string | Date | null;
  readonly isFallback?: boolean;
  readonly isStreaming?: boolean;
}

export function MessageMetaStrip(_props: MessageMetaStripProps) {
  // T-09 replaces this with the 9px mono terminal strip.
  return null;
}
