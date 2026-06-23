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
    // Wave 2: server-measured duration_ms — renders WITHOUT the ~ qualifier.
    latencySource: "server",
    // Phase-1 Research timeline: the hook always tags trace entries with the
    // loop step (`iteration`) and the input-aware completion label
    // (`resultLabel`). They are required on ToolTraceEntry, so fixtures must
    // carry them too (R19 — fixtures track the real contract, never weaken it).
    iteration: 0,
    resultLabel: "Searching documents for NVDA margin",
  },
  {
    tool: "get_quote",
    label: "Fetching quote...",
    args: { ticker: "NVDA" },
    status: "running",
    result: null,
    latencyMs: null,
    latencySource: null,
    // Still running → resultLabel falls back to the call-time label (the
    // tool_result event has not refined it yet). iteration is the loop step.
    iteration: 0,
    resultLabel: "Fetching quote...",
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

  // ── Wave 2 — server-truth latency + result_preview rendering ───────────────

  it("prefixes client-measured latency with ~ and renders server latency bare", () => {
    const trace: ToolTraceEntry[] = [
      { ...TRACE[0], tool: "server_timed", latencyMs: 146, latencySource: "server" },
      {
        ...TRACE[0],
        tool: "client_timed",
        latencyMs: 512,
        // Legacy-backend path: no duration_ms on the event → wall-clock.
        latencySource: "client",
      },
    ];
    render(<ToolTraceDrawer trace={trace} onClose={() => {}} />);

    // Server-measured: bare number — duration_ms is authoritative, no caveat.
    expect(screen.getByText("146 ms")).toBeDefined();
    // Client-measured: ~ qualifier marks the approximation honestly.
    expect(screen.getByText("~512 ms")).toBeDefined();
  });

  it("renders result_preview items as a titled list per call", () => {
    const trace: ToolTraceEntry[] = [
      {
        ...TRACE[0],
        tool: "get_entity_narrative",
        result: {
          item_count: 2,
          // Live wire shape (verified 2026-06-11): array of {id, title}.
          result_preview: [
            { id: "tool:narrative:abc", title: "Narrative: Apple Inc." },
            { id: "tool:doc:def", title: "AAPL 10-Q Q2 2026" },
          ],
        },
      },
    ];
    render(<ToolTraceDrawer trace={trace} onClose={() => {}} />);

    const preview = screen.getByTestId("tool-result-preview");
    expect(preview.textContent).toContain("Returned items");
    expect(preview.textContent).toContain("Narrative: Apple Inc.");
    expect(preview.textContent).toContain("AAPL 10-Q Q2 2026");
  });

  it("skips the preview block (no crash) when result_preview is absent or malformed", () => {
    const trace: ToolTraceEntry[] = [
      // Absent — the pre-Wave-1 backend shape.
      { ...TRACE[0], tool: "no_preview" },
      // Malformed — items missing title must be filtered, not thrown on.
      {
        ...TRACE[0],
        tool: "bad_preview",
        result: { result_preview: ["not-an-object", { id: "x" }] },
      },
    ];
    render(<ToolTraceDrawer trace={trace} onClose={() => {}} />);
    expect(screen.queryByTestId("tool-result-preview")).toBeNull();
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
        latencySource: "server",
        // Phase-1 Research timeline required fields (see TRACE above).
        iteration: 1,
        resultLabel: "Doing something...",
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
