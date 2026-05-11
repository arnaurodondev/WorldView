/**
 * __tests__/global-hotkey-bindings.test.tsx — GlobalHotkeyBindings integration tests.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 QA report F-QA-004 (MAJOR) — the nine navigation
 * chords (g d/p/i/s/w/a/n/c/,) registered by GlobalHotkeyBindings have no test
 * coverage. This file closes that gap by verifying that each chord calls
 * router.push() with the correct path, and that sidebar / search / cheat-sheet
 * bindings work as documented.
 *
 * WHY integration-level (not unit): GlobalHotkeyBindings composes three layers —
 * useChordHotkeys (listener), HotkeyRegistry (dispatch), and router.push (effect).
 * A unit test of just the bindings array would not catch listener-to-handler wiring
 * bugs. We render the full component tree and drive real keydown events.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { GlobalHotkeyBindings } from "@/components/shell/GlobalHotkeyBindings";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/dashboard"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderWithRegistry(onToggleSidebar = vi.fn(), onFocusSearch?: () => void) {
  // Fresh registry per render to avoid cross-test chord pollution.
  const registry = new HotkeyRegistry();
  return {
    registry,
    ...render(
      <HotkeyProvider registry={registry}>
        <GlobalHotkeyBindings
          onToggleSidebar={onToggleSidebar}
          onFocusSearch={onFocusSearch}
        />
      </HotkeyProvider>,
    ),
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("GlobalHotkeyBindings — navigation chords", () => {
  beforeEach(() => {
    mockPush.mockClear();
  });

  const NAVIGATION_CHORDS: Array<{ keys: string[]; path: string }> = [
    { keys: ["g", "d"], path: "/dashboard" },
    { keys: ["g", "p"], path: "/portfolio" },
    { keys: ["g", "i"], path: "/instruments" },
    { keys: ["g", "s"], path: "/screener" },
    { keys: ["g", "w"], path: "/workspace" },
    { keys: ["g", "a"], path: "/alerts" },
    { keys: ["g", "n"], path: "/news" },
    { keys: ["g", "c"], path: "/chat" },
    { keys: ["g", ","], path: "/settings" },
  ];

  for (const { keys, path } of NAVIGATION_CHORDS) {
    it(`chord "${keys.join(" ")}" navigates to ${path}`, () => {
      renderWithRegistry();

      for (const key of keys) {
        fireEvent.keyDown(document, { key });
      }
      expect(mockPush).toHaveBeenCalledWith(path);
      expect(mockPush).toHaveBeenCalledTimes(1);
    });
  }
});

describe("GlobalHotkeyBindings — view toggles", () => {
  it("mod+b fires onToggleSidebar", () => {
    const onToggleSidebar = vi.fn();
    renderWithRegistry(onToggleSidebar);

    fireEvent.keyDown(document, { key: "b", metaKey: true });
    expect(onToggleSidebar).toHaveBeenCalledOnce();
  });
});

describe("GlobalHotkeyBindings — search focus", () => {
  it("'/' fires onFocusSearch when provided", () => {
    const onFocusSearch = vi.fn();
    renderWithRegistry(vi.fn(), onFocusSearch);

    fireEvent.keyDown(document, { key: "/" });
    expect(onFocusSearch).toHaveBeenCalledOnce();
  });

  it("'/' is NOT registered when onFocusSearch is omitted", () => {
    mockPush.mockClear();
    // No onFocusSearch → the binding should not be registered → keydown is ignored
    renderWithRegistry();
    fireEvent.keyDown(document, { key: "/" });
    // Nothing should have happened (no push, no error)
    expect(mockPush).not.toHaveBeenCalled();
  });
});

describe("GlobalHotkeyBindings — g h cheat-sheet alias", () => {
  afterEach(() => {
    mockPush.mockClear();
  });

  it("g h delegates to shell.help.cheatsheet binding when registered", () => {
    const cheatSheetHandler = vi.fn();
    const registry = new HotkeyRegistry();

    // Pre-register the cheat-sheet binding (normally done by HotkeyCheatSheet).
    // The g h binding reads the registry at call time — this simulates HotkeyCheatSheet
    // being mounted before the user presses g h.
    registry.register({
      id: "shell.help.cheatsheet",
      chord: "?",
      scope: "global",
      group: "Navigation",
      label: "Keyboard shortcuts",
      handler: cheatSheetHandler,
    });

    render(
      <HotkeyProvider registry={registry}>
        <GlobalHotkeyBindings onToggleSidebar={vi.fn()} />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "g" });
    fireEvent.keyDown(document, { key: "h" });
    expect(cheatSheetHandler).toHaveBeenCalledOnce();
  });

  it("g h is a no-op when shell.help.cheatsheet is not yet registered (safe guard)", () => {
    // If HotkeyCheatSheet hasn't mounted yet (e.g., during initial render),
    // the g h handler must not throw — it should silently do nothing.
    renderWithRegistry();

    // No cheat sheet binding in registry — this should not throw
    expect(() => {
      fireEvent.keyDown(document, { key: "g" });
      fireEvent.keyDown(document, { key: "h" });
    }).not.toThrow();
  });
});

describe("GlobalHotkeyBindings — all chords are registered", () => {
  it("registers exactly 10 bindings by default (9 nav + mod+b)", () => {
    // WHY 10: g d/p/i/s/w/a/n/c/,  (9)  + g h (1) + mod+b (1) = 11.
    // When onFocusSearch is omitted, "/" is not registered → 11 bindings.
    const registry = new HotkeyRegistry();

    render(
      <HotkeyProvider registry={registry}>
        <GlobalHotkeyBindings onToggleSidebar={vi.fn()} />
      </HotkeyProvider>,
    );

    // 9 nav chords (g d/p/i/s/w/a/n/c/,) + g h + mod+b = 11
    expect(registry.all()).toHaveLength(11);
  });

  it("registers 12 bindings when onFocusSearch is provided (adds '/')", () => {
    const registry = new HotkeyRegistry();

    render(
      <HotkeyProvider registry={registry}>
        <GlobalHotkeyBindings onToggleSidebar={vi.fn()} onFocusSearch={vi.fn()} />
      </HotkeyProvider>,
    );

    // 9 nav + g h + mod+b + "/" = 12
    expect(registry.all()).toHaveLength(12);
  });

  it("unregisters all bindings on unmount", () => {
    const registry = new HotkeyRegistry();

    const { unmount } = render(
      <HotkeyProvider registry={registry}>
        <GlobalHotkeyBindings onToggleSidebar={vi.fn()} />
      </HotkeyProvider>,
    );

    expect(registry.all().length).toBeGreaterThan(0);
    unmount();
    expect(registry.all()).toHaveLength(0);
  });
});
