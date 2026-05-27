/**
 * features/chat/components/ToolCallTray.tsx — stub placeholder.
 * Full implementation lands in T-08. The type surface is the final shape;
 * the body is a minimal pass-through to ToolCallIndicator so the visual
 * regression between T-07 and T-08 is bounded to "no header / no
 * auto-collapse".
 */

"use client";

import { ToolCallIndicator, type ToolCallState } from "@/features/chat/components/ToolCallIndicator";

interface ToolCallTrayProps {
  readonly tools: ToolCallState[];
  readonly defaultCollapsed?: boolean;
}

export function ToolCallTray({ tools }: ToolCallTrayProps) {
  // T-08 will wrap this in a collapsible header with auto-collapse timing.
  if (tools.length === 0) return null;
  return <ToolCallIndicator tools={tools} />;
}
