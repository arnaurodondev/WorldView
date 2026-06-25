/**
 * features/chat/hooks/__tests__/useToolTraceChord.test.tsx
 *
 * Round 1 Foundation — ⌘D/Ctrl+D chord for the ToolTraceDrawer (PRD-0089 Q-8).
 * The security-relevant property is the NEGATIVE case: with `enabled=false`
 * (no ?debug=1 in the URL) the chord must do nothing — the drawer can never
 * be opened by a user who hasn't explicitly opted into debug mode.
 *
 * ROUND 4 HARDENING — registry migration (DESIGN_SYSTEM.md §6.12):
 * The hook no longer owns a raw document keydown listener; it registers a
 * `HotkeyBinding` (id `chat.tooltrace.drawer`, chord `mod+d`) in the central
 * hotkey registry and the shared `useChordHotkeys` dispatcher fires it. The
 * tests therefore mount the REAL dispatch pipeline (HotkeyProvider with a
 * fresh registry + a component running useChordHotkeys) and keep driving it
 * with raw document keydown events — every pre-migration behaviour assertion
 * is preserved verbatim; the new suite at the bottom additionally pins the
 * registry visibility contract (the binding exists exactly while debug mode
 * is enabled, which is what makes the `?` cheat sheet honest).
 */

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

import { TOOL_TRACE_CHORD_ID, useToolTraceChord } from "../useToolTraceChord";

// useChordHotkeys reads usePathname() — provide the chat route so any future
// page-scoped binding logic resolves the same way it does in production.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/chat"),
}));

/**
 * Dispatcher — mounts the production chord listener inside the provider.
 * WHY a component (not calling the hook in the wrapper fn): the wrapper is
 * not a React component boundary; hooks must run inside one.
 */
function Dispatcher() {
  useChordHotkeys();
  return null;
}

/**
 * makeWrapper — fresh registry per test (no cross-test binding pollution) +
 * the real HotkeyProvider + the real dispatcher. The hook under test reads
 * the registry through the provider, exactly as on the chat page.
 */
function makeWrapper(registry: HotkeyRegistry) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <HotkeyProvider registry={registry}>
        <Dispatcher />
        {children}
      </HotkeyProvider>
    );
  };
}

/** Render the hook with the full provider+dispatcher pipeline. */
function renderChord(enabled: boolean) {
  const registry = new HotkeyRegistry();
  const utils = renderHook(
    ({ enabled: e }: { enabled: boolean }) => useToolTraceChord(e),
    { initialProps: { enabled }, wrapper: makeWrapper(registry) },
  );
  return { registry, ...utils };
}

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
    const { result } = renderChord(true);
    expect(result.current.isOpen).toBe(false);

    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);

    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(false);
  });

  it("also accepts Ctrl+D (Windows/Linux)", () => {
    const { result } = renderChord(true);
    act(() => pressChord({ ctrl: true }));
    expect(result.current.isOpen).toBe(true);
  });

  it("ignores a bare 'd' keypress (no modifier)", () => {
    const { result } = renderChord(true);
    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "d", bubbles: true }),
      );
    });
    expect(result.current.isOpen).toBe(false);
  });

  it("is completely inert when disabled (Q-8 gate)", () => {
    const { result } = renderChord(false);
    act(() => pressChord({ meta: true }));
    act(() => pressChord({ ctrl: true }));
    expect(result.current.isOpen).toBe(false);
  });

  it("force-closes when the gate flips off mid-session", () => {
    // Simulates the user editing the URL from ?debug=1 to no flag while the
    // drawer is open — the trace surface must disappear with the gate.
    const { result, rerender } = renderChord(true);
    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);

    rerender({ enabled: false });
    expect(result.current.isOpen).toBe(false);
  });

  it("close() closes an open drawer", () => {
    const { result } = renderChord(true);
    act(() => pressChord({ meta: true }));
    expect(result.current.isOpen).toBe(true);
    act(() => result.current.close());
    expect(result.current.isOpen).toBe(false);
  });
});

// ── Round 4 — registry visibility contract (§6.12 no-lying invariant) ────────
//
// The `?` cheat sheet renders registry.all() verbatim. These tests pin that
// the tool-trace chord is DISCOVERABLE exactly while the debug gate is on:
// registered with the documented id/chord while enabled, absent otherwise —
// the structural guarantee that the overlay can neither advertise an unwired
// chord nor leak a debug-only chord to non-debug sessions.

describe("useToolTraceChord — hotkey registry integration (Round 4)", () => {
  it("registers the mod+d binding in the registry while enabled", () => {
    const { registry } = renderChord(true);

    const binding = registry
      .all()
      .find((b) => b.id === TOOL_TRACE_CHORD_ID);
    expect(binding).toBeDefined();
    // Canonical chord: "mod+d" (⌘D on macOS / Ctrl+D elsewhere — the
    // registry canonicalises cmd/ctrl to "mod").
    expect(binding?.chord).toBe("mod+d");
    expect(binding?.scope).toBe("global");
    // The label is what the cheat sheet shows — it must self-identify as a
    // debug surface so nobody mistakes it for a product feature.
    expect(binding?.label).toMatch(/debug/i);
  });

  it("does NOT register the binding when disabled (cheat sheet stays clean)", () => {
    const { registry } = renderChord(false);
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(false);
  });

  it("unregisters when the gate flips off and re-registers when it flips back on", () => {
    const { registry, rerender } = renderChord(true);
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(true);

    rerender({ enabled: false });
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(false);

    rerender({ enabled: true });
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(true);
  });

  it("unregisters on unmount (no leaked binding after leaving the chat page)", () => {
    const { registry, unmount } = renderChord(true);
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(true);

    unmount();
    expect(
      registry.all().some((b) => b.id === TOOL_TRACE_CHORD_ID),
    ).toBe(false);
  });
});
