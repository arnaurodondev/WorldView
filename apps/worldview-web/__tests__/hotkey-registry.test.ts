/**
 * __tests__/hotkey-registry.test.ts — Unit tests for the hotkey registry.
 *
 * PLAN-0059 W1 F-LAYOUT-001 closure: the registry is the single source of truth
 * for chord bindings. The most damaging audit signal was the StatusBar advertising
 * chords with no listener wired. The structural guarantee is that the StatusBar
 * + cheat sheet read FROM the registry — so a chord can only be advertised if
 * it is actually registered. These tests pin down the registry's contract:
 *
 *   - canonicalChord normalises Cmd/Ctrl/Meta → "mod"
 *   - register / unregister round-trips
 *   - lookup respects scope precedence (modal > input > chart > table > page > global)
 *   - lookup honours `when` predicates and `page` matchers
 *   - isPrefix detects partial matches for chord buffers
 *   - subscribe fires on changes
 *
 * NEVER edit a test to make it pass; the registry's contract is sacrosanct
 * because the cheat sheet, StatusBar, and chord listener all depend on it.
 */

import { describe, it, expect, vi } from "vitest";
import {
  HotkeyRegistry,
  canonicalChord,
  formatChordForDisplay,
  type HotkeyBinding,
  type HotkeyScope,
} from "@/lib/hotkey-registry";

// ── canonicalChord ───────────────────────────────────────────────────────────

describe("canonicalChord()", () => {
  it("lowercases the input", () => {
    expect(canonicalChord("G D")).toBe("g d");
    expect(canonicalChord("Mod+K")).toBe("mod+k");
  });

  it("aliases cmd / meta / ctrl to mod", () => {
    expect(canonicalChord("cmd+k")).toBe("mod+k");
    expect(canonicalChord("meta+k")).toBe("mod+k");
    expect(canonicalChord("ctrl+k")).toBe("mod+k");
  });

  it("preserves chord sequences with single space", () => {
    expect(canonicalChord("g  d")).toBe("g d"); // collapses double space
    expect(canonicalChord("  g  d  ")).toBe("g d"); // trims and collapses
  });

  it("preserves modifier ordering as written (no auto-sort)", () => {
    // Authors register in the order they want — listener emits in shift+mod+alt order.
    expect(canonicalChord("shift+mod+e")).toBe("shift+mod+e");
  });

  it("handles single-character chords", () => {
    expect(canonicalChord("?")).toBe("?");
    expect(canonicalChord("/")).toBe("/");
    expect(canonicalChord("d")).toBe("d");
  });
});

// ── formatChordForDisplay ─────────────────────────────────────────────────────

describe("formatChordForDisplay()", () => {
  it("renders mod as ⌘ on macOS", () => {
    expect(formatChordForDisplay("mod+k", true)).toBe("⌘K");
    expect(formatChordForDisplay("shift+mod+e", true)).toBe("⇧⌘E");
  });

  it("renders mod as Ctrl+ on non-macOS", () => {
    expect(formatChordForDisplay("mod+k", false)).toBe("Ctrl+K");
    expect(formatChordForDisplay("shift+mod+e", false)).toBe("Shift+Ctrl+E");
  });

  it("uppercases letter chords for visual prominence", () => {
    expect(formatChordForDisplay("g d", true)).toBe("G D");
    expect(formatChordForDisplay("?", true)).toBe("?");
  });

  it("renders special keys with glyphs", () => {
    expect(formatChordForDisplay("escape", true)).toBe("Esc");
    expect(formatChordForDisplay("arrowup", true)).toBe("↑");
    expect(formatChordForDisplay("space", true)).toBe("Space");
  });
});

// ── register / unregister ─────────────────────────────────────────────────────

function makeBinding(
  partial: Partial<HotkeyBinding> & Pick<HotkeyBinding, "id" | "chord">,
): HotkeyBinding {
  return {
    scope: "global",
    group: "Navigation",
    label: partial.label ?? `Test ${partial.id}`,
    handler: partial.handler ?? vi.fn(),
    ...partial,
  };
}

describe("HotkeyRegistry.register/unregister", () => {
  it("stores a binding by id and returns an unregister function", () => {
    const reg = new HotkeyRegistry();
    const unregister = reg.register(makeBinding({ id: "test.a", chord: "g a" }));
    expect(reg.all()).toHaveLength(1);
    unregister();
    expect(reg.all()).toHaveLength(0);
  });

  it("re-registering the same id replaces the previous binding (last-wins)", () => {
    const reg = new HotkeyRegistry();
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    reg.register(makeBinding({ id: "test.a", chord: "g a", handler: handler1 }));
    reg.register(makeBinding({ id: "test.a", chord: "g a", handler: handler2 }));
    expect(reg.all()).toHaveLength(1);
    // Lookup should fire the new handler.
    const found = reg.lookup("g a", new Set(["global"]), "/dashboard");
    found?.handler(new KeyboardEvent("keydown"));
    expect(handler1).not.toHaveBeenCalled();
    expect(handler2).toHaveBeenCalledOnce();
  });

  it("unregister is idempotent", () => {
    const reg = new HotkeyRegistry();
    const unregister = reg.register(makeBinding({ id: "test.a", chord: "g a" }));
    unregister();
    expect(() => unregister()).not.toThrow();
    expect(reg.all()).toHaveLength(0);
  });

  it("canonicalises stored chord strings", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "test.k", chord: "Cmd+K" }));
    // Lookup with the canonical form succeeds.
    expect(reg.lookup("mod+k", new Set(["global"]))).not.toBeNull();
    // Lookup with another alias also succeeds (canonicalChord normalises).
    expect(reg.lookup("ctrl+k", new Set(["global"]))).not.toBeNull();
  });
});

// ── lookup: scope precedence ──────────────────────────────────────────────────

describe("HotkeyRegistry.lookup() scope precedence", () => {
  it("inner-most active scope wins over outer", () => {
    const reg = new HotkeyRegistry();
    const globalHandler = vi.fn();
    const pageHandler = vi.fn();
    reg.register(
      makeBinding({ id: "global.x", chord: "x", scope: "global", handler: globalHandler }),
    );
    reg.register(
      makeBinding({ id: "page.x", chord: "x", scope: "page", handler: pageHandler }),
    );

    // Both global and page scopes active → page wins (inner).
    const both = reg.lookup("x", new Set<HotkeyScope>(["global", "page"]));
    expect(both?.id).toBe("page.x");

    // Only global active → global wins.
    const onlyGlobal = reg.lookup("x", new Set<HotkeyScope>(["global"]));
    expect(onlyGlobal?.id).toBe("global.x");
  });

  it("modal scope suppresses global chords", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "global.gd", chord: "g d", scope: "global" }));
    // No modal-scope binding registered for "g d".
    const result = reg.lookup("g d", new Set<HotkeyScope>(["global", "modal"]));
    // Modal is the highest precedence but has no matching binding → match returns null.
    expect(result).toBeNull();
  });

  it("returns null when no scope matches", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "page.d", chord: "d", scope: "page" }));
    // Only global active, but the binding is page-scoped → no match.
    const result = reg.lookup("d", new Set<HotkeyScope>(["global"]));
    expect(result).toBeNull();
  });
});

// ── lookup: page matcher ──────────────────────────────────────────────────────

describe("HotkeyRegistry.lookup() page matching", () => {
  it("undefined page matches any pathname", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "any.x", chord: "x" }));
    expect(reg.lookup("x", new Set(["global"]), "/dashboard")).not.toBeNull();
    expect(reg.lookup("x", new Set(["global"]), "/portfolio")).not.toBeNull();
  });

  it("prefix path (ending in /) matches startsWith", () => {
    const reg = new HotkeyRegistry();
    reg.register(
      makeBinding({ id: "ins.d", chord: "d", scope: "page", page: "/instruments/" }),
    );
    expect(
      reg.lookup("d", new Set<HotkeyScope>(["global", "page"]), "/instruments/AAPL"),
    ).not.toBeNull();
    expect(
      reg.lookup("d", new Set<HotkeyScope>(["global", "page"]), "/dashboard"),
    ).toBeNull();
  });

  it("exact path matches equality only", () => {
    const reg = new HotkeyRegistry();
    reg.register(
      makeBinding({ id: "dash.x", chord: "x", scope: "page", page: "/dashboard" }),
    );
    expect(
      reg.lookup("x", new Set<HotkeyScope>(["global", "page"]), "/dashboard"),
    ).not.toBeNull();
    expect(
      reg.lookup("x", new Set<HotkeyScope>(["global", "page"]), "/dashboard/sub"),
    ).toBeNull();
  });

  it("RegExp page matches as expected", () => {
    const reg = new HotkeyRegistry();
    reg.register(
      makeBinding({ id: "re.x", chord: "x", scope: "page", page: /^\/(dashboard|portfolio)/ }),
    );
    expect(
      reg.lookup("x", new Set<HotkeyScope>(["global", "page"]), "/portfolio"),
    ).not.toBeNull();
    expect(
      reg.lookup("x", new Set<HotkeyScope>(["global", "page"]), "/screener"),
    ).toBeNull();
  });
});

// ── lookup: when() predicate ──────────────────────────────────────────────────

describe("HotkeyRegistry.lookup() when() gate", () => {
  it("falsy when() makes the binding invisible", () => {
    const reg = new HotkeyRegistry();
    const enabled = { current: false };
    reg.register(
      makeBinding({ id: "gated.x", chord: "x", when: () => enabled.current }),
    );
    expect(reg.lookup("x", new Set(["global"]))).toBeNull();
    enabled.current = true;
    expect(reg.lookup("x", new Set(["global"]))).not.toBeNull();
  });
});

// ── isPrefix ──────────────────────────────────────────────────────────────────

describe("HotkeyRegistry.isPrefix()", () => {
  it("returns true when buffer is a prefix of any registered chord", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    reg.register(makeBinding({ id: "n.s", chord: "g s" }));
    expect(reg.isPrefix("g")).toBe(true);
  });

  it("returns false for a buffer that isn't a registered prefix", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    expect(reg.isPrefix("z")).toBe(false);
  });

  it("returns false for an empty buffer", () => {
    const reg = new HotkeyRegistry();
    reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    expect(reg.isPrefix("")).toBe(false);
  });

  it("rebuilds the prefix set on unregister", () => {
    const reg = new HotkeyRegistry();
    const u = reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    expect(reg.isPrefix("g")).toBe(true);
    u();
    expect(reg.isPrefix("g")).toBe(false);
  });
});

// ── subscribe ─────────────────────────────────────────────────────────────────

describe("HotkeyRegistry.subscribe()", () => {
  it("notifies subscribers on register/unregister", () => {
    const reg = new HotkeyRegistry();
    const fn = vi.fn();
    const unsub = reg.subscribe(fn);
    const bindingUnreg = reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    expect(fn).toHaveBeenCalledTimes(1);
    bindingUnreg();
    expect(fn).toHaveBeenCalledTimes(2);
    unsub();
    reg.register(makeBinding({ id: "n.s", chord: "g s" }));
    // After unsubscribing, no further calls.
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("a throwing subscriber does not break the notify chain", () => {
    const reg = new HotkeyRegistry();
    const good = vi.fn();
    reg.subscribe(() => {
      throw new Error("subscriber boom");
    });
    reg.subscribe(good);
    // Silence the error console output.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    reg.register(makeBinding({ id: "n.d", chord: "g d" }));
    expect(good).toHaveBeenCalledTimes(1);
    errSpy.mockRestore();
  });
});
