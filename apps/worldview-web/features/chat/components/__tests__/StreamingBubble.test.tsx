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
