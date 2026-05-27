/**
 * ToolCallTray.test.tsx — PLAN-0089 K Block I T-22 case 2.
 *
 * WHAT THIS GUARDS:
 *   1. The tray auto-collapses ~1.5s after the last tool finishes — without
 *      this, completed-tool rows linger and steal vertical real estate from
 *      the answer text.
 *   2. The user can click the header to manually toggle expanded/collapsed.
 *      Once they do, the auto-collapse timer must STOP fighting them.
 *   3. The header summary line reads `tool calls — N/N done`.
 *   4. Fallback rows render with the `↻ Retrying` prefix instead of a
 *      fresh spinner — visual signal that retrieval degraded.
 *
 * WHY fake timers: setTimeout is asynchronous. Without `vi.useFakeTimers()`
 * the test would either flake (race between timer + assertion) or be slow
 * (real 1.5s wait).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";

import { ToolCallTray } from "../ToolCallTray";
import type { ToolCallState } from "../ToolCallIndicator";

const RUNNING: ToolCallState = { name: "search_documents", label: "Searching…", status: "running" };
const DONE: ToolCallState = { name: "search_documents", label: "Searching…", status: "ok" };

describe("ToolCallTray (Wave K T-08)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing for an empty tool array", () => {
    // WHY: matches the "render nothing when nothing to show" rule. A blank
    // bordered box on every assistant turn would inflate vertical space.
    const { container } = render(<ToolCallTray tools={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("auto-collapses ~1.5s after the last tool finishes", () => {
    // Start with one completed tool; the auto-collapse effect should fire.
    const { container } = render(<ToolCallTray tools={[DONE]} />);
    const root = container.querySelector("[data-tool-call-tray]");
    expect(root).not.toBeNull();
    // Initially expanded (defaultCollapsed=false).
    expect(root?.getAttribute("data-collapsed")).toBe("false");
    // Advance timers past the 1.5s threshold.
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(root?.getAttribute("data-collapsed")).toBe("true");
  });

  it("does NOT auto-collapse while at least one tool is running", () => {
    const { container } = render(<ToolCallTray tools={[RUNNING, DONE]} />);
    const root = container.querySelector("[data-tool-call-tray]");
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    // Still expanded — running > 0 blocks the timer.
    expect(root?.getAttribute("data-collapsed")).toBe("false");
  });

  it("toggles when the header is clicked", () => {
    const { container } = render(<ToolCallTray tools={[RUNNING]} />);
    const root = container.querySelector("[data-tool-call-tray]");
    const header = container.querySelector("button");
    expect(header).not.toBeNull();
    fireEvent.click(header as HTMLButtonElement);
    // After user click → collapsed. The userOverride flag now keeps the
    // tray from flipping back open even if running changes.
    expect(root?.getAttribute("data-collapsed")).toBe("true");
    fireEvent.click(header as HTMLButtonElement);
    expect(root?.getAttribute("data-collapsed")).toBe("false");
  });

  it("header summary reads 'tool calls — N/N done'", () => {
    render(<ToolCallTray tools={[DONE, DONE]} />);
    // Label split into two spans ("tool calls" + the counts) so we assert
    // via textContent. Use getByRole("button") to scope the search.
    const header = screen.getByRole("button", { expanded: true });
    expect(header.textContent).toContain("tool calls");
    expect(header.textContent).toContain("2/2 done");
  });

  it("renders fallback rows with the '↻ Retrying' prefix", () => {
    // Fallback indicator from acceptance gate #13. The retry glyph + the
    // suffix "X returned empty" tells the analyst the answer is degraded.
    const fallback: ToolCallState = {
      name: "search_documents_v2",
      label: "Searching documents v2",
      status: "running",
      is_fallback: true,
      fallback_of: "search_documents",
    };
    render(<ToolCallTray tools={[fallback]} />);
    expect(
      screen.getByText(/↻ Retrying with search_documents_v2/),
    ).toBeInTheDocument();
  });
});
