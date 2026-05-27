/**
 * ToolTraceDrawer.test.tsx — PLAN-0089 K Block I T-22 case 11.
 *
 * WHAT THIS GUARDS (Q-8 lock):
 *   - The drawer returns null when `?debug=1` is absent — even if open=true.
 *     Defence in depth: a future bug that wires `open=true` accidentally
 *     must NOT leak tool internals to end users.
 *   - The drawer renders with the canonical [data-testid="tool-trace-drawer"]
 *     when debug=1 AND open=true.
 *
 * WHY mock useSearchParams: the component reads the URL via Next's
 * useSearchParams() hook (through useDebugFlag). We control the return
 * value to flip the flag on/off without hitting jsdom URL APIs.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

// Mock next/navigation BEFORE importing the component (vi.mock is hoisted
// but using a top-level reference avoids surprises).
const mockGet = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: mockGet }),
}));

import { ToolTraceDrawer } from "../ToolTraceDrawer";
import type { Message } from "@/types/api";

const baseTurn: Message = {
  message_id: "m-1",
  thread_id: "t-1",
  role: "assistant",
  content: "answer",
  created_at: "2026-05-26T14:01:24Z",
  citations: [],
};

describe("ToolTraceDrawer (Wave K T-19)", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("returns null when ?debug=1 is absent (even if open=true)", () => {
    // WHY this is the critical Q-8 lock: the URL flag is the ONLY gate.
    // If this assertion ever flips, debug surfaces could leak to prod.
    mockGet.mockReturnValue(null);
    const { container } = render(
      <ToolTraceDrawer open turn={baseTurn} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null when ?debug=1 is present but open=false", () => {
    // Both gates must be on. open=false → render nothing even with debug.
    mockGet.mockReturnValue("1");
    const { container } = render(
      <ToolTraceDrawer open={false} turn={baseTurn} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the drawer with data-testid=tool-trace-drawer when both gates are on", () => {
    mockGet.mockReturnValue("1");
    const { container } = render(
      <ToolTraceDrawer open turn={baseTurn} onClose={() => {}} />,
    );
    const drawer = container.querySelector('[data-testid="tool-trace-drawer"]');
    expect(drawer).not.toBeNull();
    // [DEBUG] badge is visible to remind the dev they're in debug mode.
    expect(drawer?.textContent).toContain("[DEBUG]");
  });
});
