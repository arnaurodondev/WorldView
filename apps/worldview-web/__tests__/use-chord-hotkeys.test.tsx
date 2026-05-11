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

  // ── F-QA-001 (BLOCKING): modal scope suppression ─────────────────────────

  it("suppresses global chords when the modal scope is active", () => {
    // PLAN-0059 W1 contract: when "modal" is in activeScopes, registry.lookup()
    // performs a modal-only short-circuit — global bindings MUST NOT fire while
    // a blocking dialog is open. Without this guard, pressing `g d` inside a
    // confirmation dialog would silently navigate away and discard the dialog state.
    const handler = vi.fn();
    registry.register(makeBinding("test.gd", "g d", handler, "global"));

    render(
      // initialScopes simulates "a modal dialog is currently open"
      <HotkeyProvider registry={registry} initialScopes={["global", "modal"]}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });
    fireEvent.keyDown(document, { key: "d" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("fires a modal-scoped binding even when modal scope is active", () => {
    // Verify the short-circuit only blocks non-modal bindings; modal bindings
    // still fire so dialogs can handle their own chords (e.g., Esc to close).
    const globalHandler = vi.fn();
    const modalHandler = vi.fn();
    registry.register(makeBinding("test.global", "x", globalHandler, "global"));
    registry.register(makeBinding("test.modal", "x", modalHandler, "modal"));

    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "modal"]}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "x" });
    expect(modalHandler).toHaveBeenCalledOnce();
    expect(globalHandler).not.toHaveBeenCalled();
  });

  // ── F-QA-005 (MAJOR): edge-case chord sequences ───────────────────────────

  it("falls back to a single-key chord when a stale prefix has no continuation", () => {
    // Covers the fallback branch in useChordHotkeys: if the chord buffer holds
    // a valid prefix ("g") but the next key doesn't continue it ("g x" has no
    // binding), the listener tries the incoming key alone as a fresh chord.
    const chordHandler = vi.fn(); // only fires for "g d"
    const fallbackHandler = vi.fn(); // fires when "x" is typed after stale "g" prefix
    registry.register(makeBinding("test.gd", "g d", chordHandler, "global"));
    registry.register(makeBinding("test.x", "x", fallbackHandler, "global"));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" }); // buffer = "g" (valid prefix of "g d")
    fireEvent.keyDown(document, { key: "x" }); // "g x" has no binding → fallback to "x"
    expect(fallbackHandler).toHaveBeenCalledOnce();
    expect(chordHandler).not.toHaveBeenCalled();
  });

  it("Escape+chord sequence: pressing a chord immediately after Escape starts fresh", () => {
    // After Escape the buffer must be fully cleared so subsequent keys begin
    // a new chord from scratch — not appended to the now-gone prefix.
    const handler = vi.fn();
    registry.register(makeBinding("test.d", "d", handler, "global"));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });   // start a prefix
    fireEvent.keyDown(document, { key: "Escape" }); // clear buffer
    fireEvent.keyDown(document, { key: "d" });   // "d" alone — should fire
    expect(handler).toHaveBeenCalledOnce();
  });

  // ── F-QA-003 (CRITICAL): IME composition guard ───────────────────────────

  it("ignores keydown events during IME composition (isComposing=true)", () => {
    // When the user is composing a CJK character (Korean/Japanese/Chinese), the
    // browser fires keydown with isComposing=true. These events MUST NOT be
    // treated as chord inputs — doing so would, for example, navigate to the
    // portfolio when a Korean user types "가" (which fires key="ArrowUp" midway).
    const handler = vi.fn();
    registry.register(makeBinding("test.d", "d", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    // Simulate an IME composition keydown — the listener must return early.
    fireEvent.keyDown(document, { key: "d", isComposing: true });
    expect(handler).not.toHaveBeenCalled();
  });

  // ── F-QA-004 (CRITICAL): Pure modifier guard ─────────────────────────────

  it("does not treat a bare modifier key as a chord (Meta/Shift/Control alone)", () => {
    // Pressing Cmd alone (before a chord like Cmd+K) fires a keydown with key="Meta".
    // The listener must silently skip it — otherwise a binding for "meta" would
    // fire every time the user raises their Cmd key.
    const handler = vi.fn();
    // Register a binding with id "test.meta" to confirm nothing fires.
    registry.register(makeBinding("test.meta", "meta", handler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    // Each of these must be discarded before the chord-matching phase.
    fireEvent.keyDown(document, { key: "Meta" });
    fireEvent.keyDown(document, { key: "Shift" });
    fireEvent.keyDown(document, { key: "Control" });
    fireEvent.keyDown(document, { key: "Alt" });
    expect(handler).not.toHaveBeenCalled();
  });

  // ── F-QA-001 (CRITICAL): Async handler fire-and-forget ───────────────────

  it("fire-and-forgets async handlers without blocking the listener", () => {
    // The listener wraps async handlers in void + .catch() — it must NOT await
    // them (that would freeze the event loop). Verify: (a) handler was called
    // synchronously, (b) a subsequent chord still fires without waiting for the
    // first promise to settle.
    let promiseResolve!: () => void;
    const asyncHandler = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          promiseResolve = resolve;
        }),
    );
    const secondHandler = vi.fn();
    registry.register(makeBinding("test.async", "a", asyncHandler));
    registry.register(makeBinding("test.second", "s", secondHandler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    // Fire "a" — async handler called, promise is pending.
    fireEvent.keyDown(document, { key: "a" });
    expect(asyncHandler).toHaveBeenCalledOnce();

    // Listener is NOT blocked — "s" fires while promise is still pending.
    fireEvent.keyDown(document, { key: "s" });
    expect(secondHandler).toHaveBeenCalledOnce();

    // Settle the promise (cleanup — avoids unhandled-promise warning in test output).
    promiseResolve();
  });

  // ── F-QA-002 (CRITICAL): Handler throw guard ─────────────────────────────

  it("catches synchronous handler throws and logs them without crashing", () => {
    // A buggy handler that throws must NOT propagate out of the keydown event.
    // Without the try/catch, a throw would silence subsequent keydown events
    // in the same test suite run (the global listener is no longer attached
    // after an uncaught exception unwinds the call stack).
    const throwingHandler = vi.fn(() => {
      throw new Error("intentional handler failure");
    });
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    registry.register(makeBinding("test.throw", "t", throwingHandler));

    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    // The keydown must not throw out of the listener.
    expect(() => fireEvent.keyDown(document, { key: "t" })).not.toThrow();
    expect(throwingHandler).toHaveBeenCalledOnce();
    // The error was logged (not silently swallowed) — 2-arg call: message + Error.
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("[hotkeys]"),
      expect.any(Error),
    );

    consoleSpy.mockRestore();
  });
});
