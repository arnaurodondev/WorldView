/**
 * features/chat/components/__tests__/ThrottledMarkdown.test.tsx
 *
 * Round 4 Hardening (perf 4a) — pins the frame-throttle contract of the
 * streaming markdown renderer:
 *
 *   1. The FIRST text renders immediately (no added first-token latency).
 *   2. Updates inside the ~33ms frame budget are NOT parsed immediately —
 *      a trailing flush renders the LATEST text when the budget elapses
 *      (tokens coalesce; none are lost).
 *   3. Rapid successive updates collapse into one flush of the newest value
 *      (intermediate strings are skipped entirely — the whole point: one
 *      markdown parse per frame, not one per token).
 *
 * WHY mock LazyMarkdownContent: same reason as StreamingBubble.test — the
 * real component goes through next/dynamic; a passthrough span lets us
 * observe exactly which text value reached the markdown boundary.
 */

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STREAM_RENDER_FRAME_MS, ThrottledMarkdown } from "../ThrottledMarkdown";

vi.mock("../LazyMarkdownContent", () => ({
  LazyMarkdownContent: ({ children }: { children?: string }) => (
    <span data-testid="markdown">{children}</span>
  ),
}));

describe("ThrottledMarkdown", () => {
  beforeEach(() => {
    // Fake timers fake Date.now() too — the component's frame budget
    // (Date.now based) and its setTimeout advance in lockstep with
    // vi.advanceTimersByTime, making the throttle fully deterministic.
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the initial text immediately (no first-token latency)", () => {
    render(<ThrottledMarkdown>Hello</ThrottledMarkdown>);
    expect(screen.getByTestId("markdown").textContent).toBe("Hello");
  });

  it("holds updates inside the frame budget, then flushes the latest text", () => {
    const { rerender } = render(<ThrottledMarkdown>Hello</ThrottledMarkdown>);

    // A token arrives 0ms after mount — inside the 33ms budget, so the
    // markdown boundary must still show the previous text (no re-parse yet).
    rerender(<ThrottledMarkdown>Hello wor</ThrottledMarkdown>);
    expect(screen.getByTestId("markdown").textContent).toBe("Hello");

    // Another token lands while the trailing flush is pending — still held.
    rerender(<ThrottledMarkdown>Hello world</ThrottledMarkdown>);
    expect(screen.getByTestId("markdown").textContent).toBe("Hello");

    // Frame budget elapses → ONE flush with the NEWEST text. The
    // intermediate "Hello wor" was never parsed (coalescing, not queueing).
    act(() => {
      vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS + 1);
    });
    expect(screen.getByTestId("markdown").textContent).toBe("Hello world");
  });

  it("flushes immediately when the frame budget has already elapsed (leading edge)", () => {
    const { rerender } = render(<ThrottledMarkdown>A</ThrottledMarkdown>);

    // Let more than a frame pass with NO updates…
    act(() => {
      vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS * 3);
    });

    // …then a token arrives: the budget is free, so it renders synchronously
    // (a slow stream must never feel throttled).
    rerender(<ThrottledMarkdown>AB</ThrottledMarkdown>);
    expect(screen.getByTestId("markdown").textContent).toBe("AB");
  });

  it("never loses the final text under a continuous token burst", () => {
    const { rerender } = render(<ThrottledMarkdown>t0</ThrottledMarkdown>);

    // Simulate a 10-token burst at 5ms cadence — well under the frame budget.
    let text = "t0";
    for (let i = 1; i <= 10; i++) {
      text = `t${i}`;
      rerender(<ThrottledMarkdown>{text}</ThrottledMarkdown>);
      act(() => {
        vi.advanceTimersByTime(5);
      });
    }

    // Drain any pending trailing flush — the LAST token must always land.
    act(() => {
      vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS + 1);
    });
    expect(screen.getByTestId("markdown").textContent).toBe("t10");
  });

  it("cleans up the pending trailing timer on unmount (no setState after unmount)", () => {
    const { rerender, unmount } = render(<ThrottledMarkdown>x</ThrottledMarkdown>);
    rerender(<ThrottledMarkdown>xy</ThrottledMarkdown>); // schedules a flush

    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    unmount();
    act(() => {
      vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS * 2);
    });
    // No "update on an unmounted component" / act warnings → timer was cleared.
    expect(errSpy).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
