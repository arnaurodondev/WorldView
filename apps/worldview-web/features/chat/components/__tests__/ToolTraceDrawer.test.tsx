/**
 * features/chat/components/__tests__/ToolTraceDrawer.test.tsx
 *
 * Round 1 Foundation — debug drawer behind ?debug=1 (PRD-0089 Q-8).
 * Pure-render component: tests assert per-call disclosure content (tool name,
 * JSON args, result, latency), the empty state, and the close wiring. The
 * gating (?debug=1 + ⌘D) is tested separately in useToolTraceChord.test.tsx
 * and end-to-end in e2e/chat-polish.spec.ts.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToolTraceDrawer } from "../ToolTraceDrawer";
import type { ToolTraceEntry } from "../../lib/types";

const TRACE: ToolTraceEntry[] = [
  {
    tool: "search_documents",
    label: "Searching documents...",
    args: { query: "NVDA margin", top_k: 5 },
    status: "ok",
    result: { item_count: 4 },
    latencyMs: 231,
  },
  {
    tool: "get_quote",
    label: "Fetching quote...",
    args: { ticker: "NVDA" },
    status: "running",
    result: null,
    latencyMs: null,
  },
];

describe("ToolTraceDrawer", () => {
  it("renders one collapsible entry per tool call with name, status and latency", () => {
    render(<ToolTraceDrawer trace={TRACE} onClose={() => {}} />);

    // The drawer testid is the e2e contract (chat-polish.spec.ts).
    expect(screen.getByTestId("tool-trace-drawer")).toBeDefined();
    expect(screen.getAllByTestId("tool-trace-entry")).toHaveLength(2);

    // Raw tool names visible (the engineer's identifier).
    expect(screen.getByText("search_documents")).toBeDefined();
    expect(screen.getByText("get_quote")).toBeDefined();

    // Latency per call — numeric in ms; running tool shows the em-dash.
    expect(screen.getByText("231 ms")).toBeDefined();
    expect(screen.getByText("—")).toBeDefined();
  });

  it("shows formatted JSON arguments and the result payload", () => {
    render(<ToolTraceDrawer trace={TRACE} onClose={() => {}} />);

    // JSON.stringify(…, null, 2) puts each key on its own line — assert via
    // substring matches so we don't over-couple to exact whitespace.
    expect(screen.getByText(/"query": "NVDA margin"/)).toBeDefined();
    expect(screen.getByText(/"top_k": 5/)).toBeDefined();
    expect(screen.getByText(/"item_count": 4/)).toBeDefined();
    // The still-running call shows the running placeholder instead of result JSON.
    expect(screen.getByText("(running…)")).toBeDefined();
  });

  it("renders the named empty state when no tools ran", () => {
    render(<ToolTraceDrawer trace={[]} onClose={() => {}} />);
    expect(screen.getByText(/No tool calls in the last turn/)).toBeDefined();
    expect(screen.queryAllByTestId("tool-trace-entry")).toHaveLength(0);
  });

  it("invokes onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<ToolTraceDrawer trace={[]} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close tool trace/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ── Round 4 a11y — dialog focus management (WCAG 2.4.3) ────────────────────
  // The drawer opens via a keyboard chord (⌘D) — focus must move INTO the
  // dialog so the keyboard user who just opened it can operate it, and must
  // RETURN to wherever they were when it closes.

  it("moves focus into the drawer on open and returns it on close", () => {
    // Simulate the real opening context: the user's focus is on a control
    // (the chat composer / a chip) when they hit ⌘D.
    const trigger = document.createElement("button");
    trigger.textContent = "outside control";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(<ToolTraceDrawer trace={TRACE} onClose={() => {}} />);

    // Open: focus lands on the labelled dialog container (tabIndex=-1 —
    // programmatic focus only, not a Tab stop).
    expect(document.activeElement).toBe(screen.getByTestId("tool-trace-drawer"));

    // Close (chord toggle / X — both unmount the drawer): focus returns to
    // the original control so the keyboard flow is unbroken.
    unmount();
    expect(document.activeElement).toBe(trigger);

    trigger.remove();
  });

  it("auto-expands errored calls and keeps healthy calls collapsed", () => {
    const trace: ToolTraceEntry[] = [
      { ...TRACE[0], tool: "ok_tool", status: "ok" },
      {
        tool: "broken_tool",
        label: "Doing something...",
        args: {},
        status: "error",
        result: { error: "timeout" },
        latencyMs: 5000,
      },
    ];
    render(<ToolTraceDrawer trace={trace} onClose={() => {}} />);

    const entries = screen.getAllByTestId("tool-trace-entry");
    // <details open> only on the errored entry — the thing the engineer came
    // to inspect is pre-expanded; healthy calls stay out of the way.
    expect((entries[0] as HTMLDetailsElement).open).toBe(false);
    expect((entries[1] as HTMLDetailsElement).open).toBe(true);
  });
});
