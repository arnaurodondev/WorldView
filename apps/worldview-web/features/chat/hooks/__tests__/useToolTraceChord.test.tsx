/**
 * features/chat/hooks/__tests__/useToolTraceChord.test.tsx
 *
 * Round 1 Foundation — ⌘D/Ctrl+D chord for the ToolTraceDrawer (PRD-0089 Q-8).
 * The security-relevant property is the NEGATIVE case: with `enabled=false`
 * (no ?debug=1 in the URL) the chord must do nothing — the drawer can never
 * be opened by a user who hasn't explicitly opted into debug mode.
 */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useToolTraceChord } from "../useToolTraceChord";

/** Dispatch a ⌘D keydown on document — what the user's keyboard produces. */
function pressChord(opts: { meta?: boolean; ctrl?: boolean } = { meta: true }) {
  document.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: "d",
      metaKey: opts.meta ?? false,
      ctrlKey: opts.ctrl ?? false,
      bubbles: true,
      cancelable: true,
    }),
  );
}

describe("useToolTraceChord", () => {
  it("toggles open/closed on ⌘D when enabled", () => {
    const { result } = renderHook(() => useToolTraceChord(true));
    expect(result.current.isOpen).toBe(false);

    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);

    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(false);
  });

  it("also accepts Ctrl+D (Windows/Linux)", () => {
    const { result } = renderHook(() => useToolTraceChord(true));
    act(() => pressChord({ ctrl: true }));
    expect(result.current.isOpen).toBe(true);
  });

  it("ignores a bare 'd' keypress (no modifier)", () => {
    const { result } = renderHook(() => useToolTraceChord(true));
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true }),
      );
    });
    expect(result.current.isOpen).toBe(false);
  });

  it("is completely inert when disabled (Q-8 gate)", () => {
    const { result } = renderHook(() => useToolTraceChord(false));
    act(() => pressChord({ meta: true }));
    act(() => pressChord({ ctrl: true }));
    expect(result.current.isOpen).toBe(false);
  });

  it("force-closes when the gate flips off mid-session", () => {
    // Simulates the user editing the URL from ?debug=1 to no flag while the
    // drawer is open — the trace surface must disappear with the gate.
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useToolTraceChord(enabled),
      { initialProps: { enabled: true } },
    );
    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);

    rerender({ enabled: false });
    expect(result.current.isOpen).toBe(false);
  });

  it("close() closes an open drawer", () => {
    const { result } = renderHook(() => useToolTraceChord(true));
    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);
    act(() => result.current.close());
    expect(result.current.isOpen).toBe(false);
  });
});
