"use client";
// WHY "use client": holds throttle state + timers — browser-only concerns.
// This also keeps MessageBubble.tsx a Server Component (it may render Client
// Components like this one, but cannot use hooks itself).

/**
 * features/chat/components/ThrottledMarkdown.tsx — frame-throttled markdown
 * renderer for the in-flight streaming bubble (Round 4 Hardening, perf 4a).
 *
 * THE HOT SPOT (measured by reasoning over the render path, then pinned by
 * the unit test):
 * SSE tokens arrive every ~20-50ms. StreamingBubble previously passed the
 * accumulated text straight into <LazyMarkdownContent> — react-markdown has
 * no incremental mode, so EVERY token re-parsed the ENTIRE answer text from
 * scratch (remark parse → mdast → hast → React elements). Parse cost grows
 * linearly with answer length, so the per-token cost climbs as the answer
 * streams: by the tail of a 500-token research answer the page was doing a
 * full multi-KB markdown parse 20-50 times per second — the classic
 * quadratic-ish streaming-markdown trap.
 *
 * THE FIX: cap the markdown re-parse rate at one per ~33ms frame.
 *   - The FIRST text value renders immediately (initial state = prop), so
 *     perceived first-token latency is unchanged.
 *   - Subsequent updates flush immediately when ≥33ms have passed since the
 *     last flush, otherwise a single trailing timer flushes the LATEST text
 *     when the frame budget elapses — no token is ever lost, the bubble just
 *     coalesces 1-2 tokens per paint instead of parsing per token.
 *   - 33ms ≈ 30fps: comfortably smoother than human reading speed for a
 *     typewriter effect, while halving-to-quartering the parse work at the
 *     typical 20-50ms token cadence.
 *
 * WHY THROTTLE HERE (component boundary) AND NOT IN useChatStream:
 * The hook's per-token setStreaming() is cheap (string state) and its timing
 * semantics are pinned by ~30 hook tests (mid-stream assertions await state
 * after each pushed chunk). Throttling the STATE would have changed the
 * hook's observable contract and weakened those tests; throttling the PARSE
 * at the render boundary keeps the hook contract intact and contains the
 * optimisation to exactly the expensive subtree.
 *
 * WHY useMemo ON THE RETURNED ELEMENT: the parent (StreamingBubble → page)
 * still re-renders at token cadence. Memoising the element on the THROTTLED
 * text means React sees the identical element reference between flushes and
 * bails out of the LazyMarkdownContent subtree entirely — the markdown tree
 * is only reconciled when the displayed text actually changes.
 *
 * NOT USED FOR SETTLED MESSAGES: MessageBubble renders LazyMarkdownContent
 * directly — settled content parses exactly once per message, throttling
 * there would only add latency for zero saved work.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { LazyMarkdownContent } from "./LazyMarkdownContent";

/**
 * One render frame at ~30fps. Exported so the unit test asserts against the
 * same constant instead of duplicating the number.
 */
export const STREAM_RENDER_FRAME_MS = 33;

interface ThrottledMarkdownProps {
  /** The full accumulated streaming text (updated per SSE token upstream). */
  children: string;
}

export function ThrottledMarkdown({ children: text }: ThrottledMarkdownProps) {
  // Initial state = the first prop value → the first token renders with NO
  // added latency (the throttle only applies to subsequent updates).
  const [displayText, setDisplayText] = useState(text);

  // latestRef always holds the newest prop so a pending trailing flush picks
  // up everything that arrived while the timer was waiting (no lost tokens).
  const latestRef = useRef(text);
  latestRef.current = text;

  // Wall-clock of the last flush. Date.now() (not performance.now()) so fake
  // timers in tests advance it deterministically alongside setTimeout.
  const lastFlushRef = useRef(Date.now());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Nothing new to show — this effect also re-runs after our own flush
    // (displayText changed); the equality guard makes that re-run a no-op.
    if (text === displayText) return;

    const now = Date.now();
    const sinceLastFlush = now - lastFlushRef.current;

    if (sinceLastFlush >= STREAM_RENDER_FRAME_MS) {
      // Frame budget already elapsed — flush synchronously (leading edge).
      lastFlushRef.current = now;
      setDisplayText(text);
      return;
    }

    // Inside the frame budget — schedule ONE trailing flush for the remainder
    // of the frame. If a timer is already pending, do nothing: it will read
    // latestRef and render whatever is newest when it fires.
    if (timerRef.current !== null) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      lastFlushRef.current = Date.now();
      setDisplayText(latestRef.current);
    }, STREAM_RENDER_FRAME_MS - sinceLastFlush);
  }, [text, displayText]);

  // Unmount-only cleanup. Deliberately NOT part of the effect above — a
  // per-update cleanup would cancel the trailing timer on every new token,
  // starving the flush forever under a continuous token stream.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  // Element identity is stable until displayText changes → parent re-renders
  // (per token) skip the markdown subtree via React's same-element bailout.
  return useMemo(
    () => <LazyMarkdownContent size="compact">{displayText}</LazyMarkdownContent>,
    [displayText],
  );
}
