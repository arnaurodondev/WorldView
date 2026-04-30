/**
 * __tests__/use-chord-hotkeys.test.tsx — Chord listener integration tests.
 *
 * Validates the contract that closes F-LAYOUT-001:
 *   - Single-letter chord fires its handler.
 *   - Two-key chord (g d) fires after second key arrives.
 *   - Buffer resets after 1.2s of inactivity.
 *   - Suspends inside text inputs.
 *   - Modifier chords (Cmd+K) fire even inside inputs.
 *   - Active scope precedence is respected (page > global).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";
import { HotkeyRegistry, type HotkeyBinding } from "@/lib/hotkey-registry";

// Wrapper that mounts the hook so tests can drive keypresses on document.
function ListenerHost() {
  useChordHotkeys();
  return null;
}

function makeBinding(
  id: string,
  chord: string,
  handler: HotkeyBinding["handler"],
  scope: HotkeyBinding["scope"] = "global",
): HotkeyBinding {
  return {
    id,
    chord,
    scope,
    group: "Navigation",
    label: id,
    handler,
  };
}

describe("useChordHotkeys", () => {
  let registry: HotkeyRegistry;

  beforeEach(() => {
    registry = new HotkeyRegistry();
    vi.useFakeTimers();
  });

  afterEach(() => {
    registry.clear();
    vi.useRealTimers();
  });

  it("fires the handler when a single-letter chord is pressed", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.q", "q", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "q" });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("fires after the second key of a chord", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.gd", "g d", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });
    expect(handler).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "d" });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("resets the chord buffer after 1.2s of inactivity", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.gd", "g d", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });
    // Advance timer past the 1.2s reset window.
    act(() => {
      vi.advanceTimersByTime(1300);
    });
    fireEvent.keyDown(document, { key: "d" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("suspends inside <input type='text'> for plain letter chords", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.q", "q", handler));

    const { container } = render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <input type="text" data-testid="text-input" />
      </HotkeyProvider>,
    );

    const input = container.querySelector('[data-testid="text-input"]') as HTMLInputElement;
    input.focus();
    fireEvent.keyDown(input, { key: "q" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("does NOT suspend modifier chords inside inputs (Cmd+K still fires)", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.modk", "mod+k", handler));

    const { container } = render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <input type="text" data-testid="text-input" />
      </HotkeyProvider>,
    );

    const input = container.querySelector('[data-testid="text-input"]') as HTMLInputElement;
    input.focus();
    fireEvent.keyDown(input, { key: "k", metaKey: true });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does NOT suspend on checkbox inputs (only text-entry types)", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.q", "q", handler));

    const { container } = render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <input type="checkbox" data-testid="cb" />
      </HotkeyProvider>,
    );

    const cb = container.querySelector('[data-testid="cb"]') as HTMLInputElement;
    cb.focus();
    fireEvent.keyDown(cb, { key: "q" });
    expect(handler).toHaveBeenCalledOnce();
  });

  it("page-scoped binding preempts global binding when both match", () => {
    const globalHandler = vi.fn();
    const pageHandler = vi.fn();
    registry.register(makeBinding("global.x", "x", globalHandler, "global"));
    registry.register(makeBinding("page.x", "x", pageHandler, "page"));

    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "x" });
    expect(pageHandler).toHaveBeenCalledOnce();
    expect(globalHandler).not.toHaveBeenCalled();
  });

  it("ignores unmatched chords (no handler call, no error)", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.q", "q", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "z" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("Escape clears any pending chord buffer", () => {
    const handler = vi.fn();
    registry.register(makeBinding("test.gd", "g d", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(document, { key: "d" });
    // After Escape the buffer was cleared, so "d" alone is no match.
    expect(handler).not.toHaveBeenCalled();
  });
});
