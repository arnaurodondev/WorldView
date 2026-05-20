/**
 * app/(app)/chat/loading.tsx — Chat page skeleton (CRIT-005 / FR-9.1)
 *
 * WHY THIS EXISTS: /chat loads thread history from S8 rag-chat which requires
 * auth + a DB round-trip. The skeleton mirrors the chat layout:
 * - Flex-1 scrollable message area with alternating user/assistant bubbles
 * - Fixed input bar at the bottom (always visible)
 *
 * WHY alternating widths: user messages (right-aligned, w-1/2) alternate with
 * assistant responses (left-aligned, w-3/4) — matches the actual chat layout
 * so there's no jarring shift when real messages load.
 */

import { Skeleton } from "@/components/ui/skeleton";

export default function ChatLoading() {
  return (
    <div className="flex flex-col h-full">
      {/* Message area: fills remaining height, clipped if overflow */}
      <div className="flex-1 flex flex-col gap-2 p-3 overflow-hidden">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton
            key={i}
            // WHY alternating: even rows = assistant (wide, left); odd = user (narrow, right)
            className={`h-[60px] rounded-[2px] ${i % 2 === 0 ? "w-3/4" : "w-1/2 self-end"}`}
          />
        ))}
      </div>
      {/* Input bar: always at bottom, same height as the real textarea */}
      <div className="border-t border-border p-2">
        <Skeleton className="h-[36px] w-full rounded-[2px]" />
      </div>
    </div>
  );
}
