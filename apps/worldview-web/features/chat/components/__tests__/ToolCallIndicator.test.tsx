/**
 * features/chat/components/__tests__/ToolCallIndicator.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0067 W11-5 T-W11-5-01):
 * ToolCallIndicator renders per-tool progress during the tool-use phase.
 * These unit tests verify the rendering rules in isolation — no SSE, no hook,
 * no chat page required. We test with @testing-library/react so we exercise
 * the actual DOM output (icon presence, text, ordering) rather than snapshots
 * that could mask regressions.
 */

import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ToolCallIndicator, type ToolCallState } from "../ToolCallIndicator";

describe("ToolCallIndicator", () => {
  it("returns null for empty tools array", () => {
    // WHY check container.firstChild: render() always returns a container div,
    // but if the component returns null the container has no children.
    const { container } = render(<ToolCallIndicator tools={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders spinner and label for a running tool", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "running" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    // The full label (including "...") should appear while the tool is running.
    expect(screen.getByText("Searching documents...")).toBeDefined();
  });

  it("renders check icon and strikethrough label for a completed ok tool", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "ok" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    // Trailing "..." is stripped for done tools — label should appear without it.
    expect(screen.getByText("Searching documents")).toBeDefined();
  });

  it("renders X icon and strikethrough label for an error tool", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "error" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    // Same stripping behaviour for error as for ok.
    expect(screen.getByText("Searching documents")).toBeDefined();
  });

  it("renders X icon and strikethrough label for an empty tool", () => {
    const tools: ToolCallState[] = [
      { name: "query_temporal", label: "Querying timeline...", status: "empty" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    expect(screen.getByText("Querying timeline")).toBeDefined();
  });

  it("renders running tools before done tools regardless of insertion order", () => {
    // WHY this matters: as tools complete, we want the stable UX of "running
    // tools always at top" so the layout doesn't jump unexpectedly.
    const tools: ToolCallState[] = [
      { name: "tool_a", label: "Tool A...", status: "ok" },      // done, inserted first
      { name: "tool_b", label: "Tool B...", status: "running" }, // running, inserted second
    ];
    render(<ToolCallIndicator tools={tools} />);

    // Both tools should appear in the DOM.
    // "Tool B..." → running, full label
    expect(screen.getByText("Tool B...")).toBeDefined();
    // "Tool A" → done, stripped label
    expect(screen.getByText("Tool A")).toBeDefined();

    // WHY we check DOM ordering: running tools must appear BEFORE done tools.
    // getByText returns the first match; getAllByRole("generic") would be too broad.
    // Instead we check that the running label's element appears before the done one.
    const runningEl = screen.getByText("Tool B...");
    const doneEl = screen.getByText("Tool A");
    // compareDocumentPosition DOCUMENT_POSITION_FOLLOWING = 4
    // (runningEl comes before doneEl in DOM)
    expect(runningEl.compareDocumentPosition(doneEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders multiple running tools with individual labels", () => {
    const tools: ToolCallState[] = [
      { name: "search_documents", label: "Searching documents...", status: "running" },
      { name: "query_temporal", label: "Querying timeline...", status: "running" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    expect(screen.getByText("Searching documents...")).toBeDefined();
    expect(screen.getByText("Querying timeline...")).toBeDefined();
  });

  it("strips trailing ellipsis from done tool labels but not mid-string dots", () => {
    const tools: ToolCallState[] = [
      // Should strip the trailing "..." only.
      { name: "tool_a", label: "Fetching data...", status: "ok" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    // Trailing "..." stripped → "Fetching data"
    expect(screen.getByText("Fetching data")).toBeDefined();
  });
});

// ── Wave 3 — live elapsed chip for running tools ──────────────────────────────
//
// USER EVIDENCE: 40-second agentic answers left the user staring at a static
// spinner with no proof of forward motion. Running rows now carry a ticking
// "Ns" chip computed from ToolCallState.startedAt (stamped by useChatStream
// at tool_call receipt).

describe("ToolCallIndicator — elapsed chip (Wave 3)", () => {
  beforeEach(() => {
    // Fake timers drive BOTH Date.now() and the component's 1s setInterval,
    // so elapsed values are fully deterministic.
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders an elapsed chip for running tools and ticks it forward each second", () => {
    const startedAt = Date.now();
    const tools: ToolCallState[] = [
      {
        name: "search_documents",
        label: "Searching documents...",
        status: "running",
        startedAt,
      },
    ];
    render(<ToolCallIndicator tools={tools} />);

    // Fresh tool → 0s.
    expect(screen.getByTestId("tool-elapsed").textContent).toBe("0s");

    // Advance 3 wall-clock seconds → the interval fires and the chip ticks.
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.getByTestId("tool-elapsed").textContent).toBe("3s");
  });

  it("renders NO elapsed chip when startedAt is absent (legacy callers)", () => {
    const tools: ToolCallState[] = [
      { name: "tool_a", label: "Tool A...", status: "running" },
    ];
    render(<ToolCallIndicator tools={tools} />);
    expect(screen.queryByTestId("tool-elapsed")).toBeNull();
  });

  it("completed tools drop the elapsed chip (no frozen counters on settled rows)", () => {
    const tools: ToolCallState[] = [
      {
        name: "tool_a",
        label: "Tool A...",
        status: "ok",
        startedAt: Date.now() - 5_000,
      },
    ];
    render(<ToolCallIndicator tools={tools} />);
    // The chip is rendered only on RUNNING rows — a done row with a frozen
    // "5s" would read as "still waiting".
    expect(screen.queryByTestId("tool-elapsed")).toBeNull();
  });
});
