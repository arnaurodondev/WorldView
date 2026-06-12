/**
 * features/chat/components/__tests__/StreamingBubble.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0067 W11-5 T-W11-5-03):
 * StreamingBubble now accepts `activeTools` and renders ToolCallIndicator
 * above the streaming text. These tests verify the wiring is correct —
 * that tool indicators appear when tools are active and are absent when not.
 *
 * WHY NOT a full integration test: StreamingBubble is a pure render
 * component (no hooks, no SSE). Unit tests with @testing-library/react
 * cover the wiring without needing a full chat page setup.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StreamingBubble } from "../MessageBubble";
import type { ToolCallState } from "../ToolCallIndicator";
import type { StreamingMessage } from "../../lib/types";

// WHY mock LazyMarkdownContent: it uses next/dynamic which triggers dynamic
// import resolution in tests. A simple mock returns the children as plain text
// so we can focus on testing StreamingBubble's own rendering logic.
vi.mock("../LazyMarkdownContent", () => ({
  LazyMarkdownContent: ({ children }: { children?: string }) => (
    <span data-testid="markdown">{children}</span>
  ),
}));

const baseStreaming: StreamingMessage = {
  text: "Hello from the assistant",
  active: true,
};

describe("StreamingBubble", () => {
  it("renders streaming text without tool indicators when activeTools is empty", () => {
    render(<StreamingBubble streaming={baseStreaming} activeTools={[]} />);

    // The streaming text should appear.
    expect(screen.getByTestId("markdown").textContent).toBe("Hello from the assistant");

    // No tool-activity region — no tools are active.
    expect(screen.queryByLabelText("Tool activity")).toBeNull();
  });

  it("renders tool indicators above text when activeTools has running tools", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "running" },
    ];
    render(<StreamingBubble streaming={baseStreaming} activeTools={tools} />);

    // Tool label should appear.
    expect(screen.getByText("Searching documents...")).toBeDefined();

    // Streaming text should also appear (tools don't replace the text).
    expect(screen.getByTestId("markdown").textContent).toBe("Hello from the assistant");
  });

  it("renders tool indicators when activeTools is omitted (defaults to empty)", () => {
    // WHY: activeTools has a default of [] so callers that haven't upgraded
    // to W11-5 yet still work without passing the prop.
    render(<StreamingBubble streaming={baseStreaming} />);
    expect(screen.queryByLabelText("Tool activity")).toBeNull();
  });

  it("renders multiple tool indicators when multiple tools are active", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "running" },
      { name: "query_temporal", label: "Querying timeline...", status: "ok" },
    ];
    render(<StreamingBubble streaming={baseStreaming} activeTools={tools} />);

    expect(screen.getByText("Searching documents...")).toBeDefined();
    // "Querying timeline" (no trailing "...") — done tool, ellipsis stripped.
    expect(screen.getByText("Querying timeline")).toBeDefined();
  });
});

// ── Round 1 Foundation — no flash of empty assistant bubble ──────────────────

describe("StreamingBubble — pre-first-token state", () => {
  it("shows a typing indicator inside the bubble when no text and no tools yet", () => {
    // The instant after Send (before the first SSE event) streaming.text is ""
    // and activeTools is empty — the old render produced an EMPTY bubble.
    render(<StreamingBubble streaming={{ text: "", active: true }} activeTools={[]} />);

    // Typing dots present…
    expect(screen.getByLabelText("AI is generating a response")).toBeDefined();
    // …and no empty markdown container is mounted (the flash).
    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("hides the typing dots once tools are active (spinners already signal progress)", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "running" },
    ];
    render(<StreamingBubble streaming={{ text: "", active: true }} activeTools={tools} />);

    // Tool indicator visible, dots gone — one progress signal at a time.
    expect(screen.getByText("Searching documents...")).toBeDefined();
    expect(screen.queryByLabelText("AI is generating a response")).toBeNull();
  });

  it("replaces the dots with markdown text when the first token arrives", () => {
    render(
      <StreamingBubble streaming={{ text: "First tok", active: true }} activeTools={[]} />,
    );
    expect(screen.getByTestId("markdown").textContent).toBe("First tok");
    expect(screen.queryByLabelText("AI is generating a response")).toBeNull();
  });
});

// ── Wave 3 — streaming-paint regression ───────────────────────────────────────
//
// USER-REPORTED BUG (2026-06-11): "streaming is not working — nothing
// displays until the end". Root cause was transport-level (the Next rewrite
// proxy gzip-buffered the SSE stream; fixed by app/api/v1/chat/[...path]/
// route.ts), but this test pins the RENDER side of the contract forever:
// when token updates DO reach the component, the visible text must update
// DURING the stream — within one ThrottledMarkdown frame (~33ms) — never
// only at stream end. If a future memo/throttle change swallows mid-stream
// paints, this fails.
//
// NOTE: LazyMarkdownContent is mocked above, but ThrottledMarkdown (the
// throttle/memo layer under suspicion) is NOT — its real timer logic runs
// against vitest fake timers.

import { act } from "@testing-library/react";
import { STREAM_RENDER_FRAME_MS } from "../ThrottledMarkdown";

describe("StreamingBubble — streaming-paint regression (Wave 3)", () => {
  it("paints each token batch DURING the stream, within one throttle frame", () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(
        <StreamingBubble streaming={{ text: "Apple", active: true }} />,
      );
      // First token batch renders immediately (no added latency).
      expect(screen.getByTestId("markdown").textContent).toBe("Apple");

      // Simulate the SSE cadence: a new accumulated text every ~20ms.
      rerender(
        <StreamingBubble streaming={{ text: "Apple is", active: true }} />,
      );
      // Inside the 33ms frame budget the throttle may hold the update…
      act(() => {
        vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS);
      });
      // …but after ONE frame it MUST be visible — mid-stream, no done event,
      // stream still active. This is the "tokens appear while streaming"
      // contract.
      expect(screen.getByTestId("markdown").textContent).toBe("Apple is");

      rerender(
        <StreamingBubble
          streaming={{ text: "Apple is doing fine", active: true }}
        />,
      );
      act(() => {
        vi.advanceTimersByTime(STREAM_RENDER_FRAME_MS);
      });
      expect(screen.getByTestId("markdown").textContent).toBe(
        "Apple is doing fine",
      );

      // The cursor is visible the whole time — the bubble reads as live.
      expect(document.querySelector(".bg-primary.align-middle")).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("running tool indicators stay visible while text streams below them", () => {
    // The 40s-wait scenario: tools visible AND text flowing — neither
    // replaces the other.
    const tools: ToolCallState[] = [
      {
        name: "get_entity_news",
        label: "get_entity_news...",
        status: "running",
        startedAt: Date.now(),
      },
    ];
    render(
      <StreamingBubble
        streaming={{ text: "Partial answer", active: true }}
        activeTools={tools}
      />,
    );
    expect(screen.getByLabelText("Tool activity")).toBeDefined();
    expect(screen.getByText("get_entity_news...")).toBeDefined();
    // Tool name (precise identifier) + elapsed chip both render.
    expect(screen.getByText("get_entity_news")).toBeDefined();
    expect(screen.getByTestId("tool-elapsed")).toBeDefined();
    expect(screen.getByTestId("markdown").textContent).toBe("Partial answer");
  });
});
