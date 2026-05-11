/**
 * __tests__/hotkey-context.test.tsx — HotkeyProvider / HotkeyContext unit tests.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 QA report F-QA-003 (CRITICAL) — the scope
 * push/pop ref-counting logic has no test coverage. Incorrect ref-counts cause
 * incorrect scope activation: one pop of a doubly-pushed scope would deactivate
 * it prematurely, enabling global chords to fire while a dialog is still open.
 *
 * COVERAGE:
 *   - Initial scope set ("global" always present)
 *   - Pushing a scope adds it to activeScopes
 *   - Ref-counting: double-push requires double-pop
 *   - "global" scope cannot be permanently removed (safety-net useEffect)
 *   - initialScopes prop overrides defaults
 *   - useHotkeyScope() throws outside a provider
 *   - useHotkeyBindings() returns live registry snapshot
 */

import { describe, it, expect, vi } from "vitest";
import React, { useEffect } from "react";
import { render, act } from "@testing-library/react";
import { HotkeyProvider, useHotkeyScope, useHotkeyBindings } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import type { HotkeyScope } from "@/lib/hotkey-registry";

// WHY: usePathname is used inside useChordHotkeys which some consumers mount.
// HotkeyContext itself doesn't use it, but tests that mount children depending
// on it need the mock. We mock it globally in this file for safety.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

// ── Test helpers ──────────────────────────────────────────────────────────────

/**
 * ScopeReader — renders the current activeScopes as JSON in a data attribute
 * so we can inspect them without triggering console.log noise.
 */
function ScopeReader({ label }: { label?: string }) {
  const { activeScopes } = useHotkeyScope();
  return (
    <div
      data-testid={label ?? "scope-reader"}
      data-scopes={JSON.stringify([...activeScopes].sort())}
    />
  );
}

/**
 * ScopePusher — pushes a scope on mount and pops on unmount. Used to simulate
 * component lifecycle (e.g., a dialog opening/closing).
 */
function ScopePusher({
  scope,
  children,
}: {
  scope: HotkeyScope;
  children?: React.ReactNode;
}) {
  const { pushScope, popScope } = useHotkeyScope();
  useEffect(() => {
    pushScope(scope);
    return () => popScope(scope);
  }, [scope, pushScope, popScope]);
  return <>{children}</>;
}

function readScopes(testId = "scope-reader"): string[] {
  const el = document.querySelector(`[data-testid="${testId}"]`);
  if (!el) return [];
  return JSON.parse(el.getAttribute("data-scopes") ?? "[]");
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HotkeyProvider — initial scope state", () => {
  it("starts with only 'global' scope active by default", () => {
    render(
      <HotkeyProvider>
        <ScopeReader />
      </HotkeyProvider>,
    );
    const scopes = readScopes();
    expect(scopes).toEqual(["global"]);
  });

  it("respects the initialScopes prop", () => {
    render(
      <HotkeyProvider initialScopes={["global", "page"]}>
        <ScopeReader />
      </HotkeyProvider>,
    );
    const scopes = readScopes();
    expect(scopes).toContain("global");
    expect(scopes).toContain("page");
    expect(scopes).toHaveLength(2);
  });

  it("exposes the bound registry via context", () => {
    const registry = new HotkeyRegistry();
    let ctxRegistry: HotkeyRegistry | null = null;

    function RegistryReader() {
      const { registry: r } = useHotkeyScope();
      ctxRegistry = r;
      return null;
    }

    render(
      <HotkeyProvider registry={registry}>
        <RegistryReader />
      </HotkeyProvider>,
    );
    expect(ctxRegistry).toBe(registry);
  });
});

describe("HotkeyProvider — pushScope / popScope", () => {
  it("pushing a scope adds it to activeScopes", () => {
    render(
      <HotkeyProvider>
        <ScopePusher scope="modal">
          <ScopeReader />
        </ScopePusher>
      </HotkeyProvider>,
    );
    const scopes = readScopes();
    expect(scopes).toContain("modal");
    expect(scopes).toContain("global");
  });

  it("popping a scope (once pushed) removes it from activeScopes", async () => {
    const { rerender } = render(
      <HotkeyProvider>
        <ScopePusher scope="chart">
          <ScopeReader />
        </ScopePusher>
      </HotkeyProvider>,
    );
    expect(readScopes()).toContain("chart");

    // Unmount ScopePusher (simulates closing a chart panel) — pops "chart"
    rerender(
      <HotkeyProvider>
        <ScopeReader />
      </HotkeyProvider>,
    );
    expect(readScopes()).not.toContain("chart");
  });

  it("ref-counting: double-push requires two pops before scope deactivates", async () => {
    // This is the nested-dialogs case: two modals open → both must close before
    // modal scope is removed. Without ref-counting, the first pop would remove
    // "modal" and global chords would fire while the second modal is still visible.
    let popFirst!: () => void;
    let popSecond!: () => void;

    function DoublePusher() {
      const { pushScope, popScope } = useHotkeyScope();
      useEffect(() => {
        // Push twice, simulating two nested components each pushing the same scope.
        pushScope("modal");
        pushScope("modal");
        popFirst = () => act(() => { popScope("modal"); });
        popSecond = () => act(() => { popScope("modal"); });
      }, [pushScope, popScope]);
      return null;
    }

    render(
      <HotkeyProvider>
        <DoublePusher />
        <ScopeReader />
      </HotkeyProvider>,
    );

    // After two pushes, "modal" is in activeScopes
    expect(readScopes()).toContain("modal");

    // First pop: ref count 2→1 — scope stays active
    popFirst();
    expect(readScopes()).toContain("modal");

    // Second pop: ref count 1→0 — scope is now removed
    popSecond();
    expect(readScopes()).not.toContain("modal");
  });

  it("'global' scope cannot be permanently removed — safety net restores it", async () => {
    // The HotkeyProvider has a useEffect safety net: if someone accidentally
    // pops "global" it gets re-added on the next render cycle. This prevents
    // a programming error from silently disabling all global chords.
    let triggerPop!: () => void;

    function GlobalPopper() {
      const { popScope } = useHotkeyScope();
      triggerPop = () => act(() => { popScope("global"); });
      return null;
    }

    render(
      <HotkeyProvider>
        <GlobalPopper />
        <ScopeReader />
      </HotkeyProvider>,
    );

    expect(readScopes()).toContain("global");
    triggerPop(); // pop "global"
    // After re-render the safety-net useEffect re-adds it
    expect(readScopes()).toContain("global");
  });

  it("multiple distinct scopes can be active simultaneously", () => {
    render(
      <HotkeyProvider>
        <ScopePusher scope="chart">
          <ScopePusher scope="page">
            <ScopeReader />
          </ScopePusher>
        </ScopePusher>
      </HotkeyProvider>,
    );
    const scopes = readScopes();
    expect(scopes).toContain("global");
    expect(scopes).toContain("chart");
    expect(scopes).toContain("page");
  });
});

describe("useHotkeyScope() — error guard", () => {
  it("throws when called outside a HotkeyProvider", () => {
    function BadConsumer() {
      useHotkeyScope();
      return null;
    }

    // Suppress React's error boundary console output during this test
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<BadConsumer />)).toThrow(/useHotkeyScope.*HotkeyProvider/);
    consoleSpy.mockRestore();
  });
});

describe("useHotkeyBindings() — live registry snapshot", () => {
  it("returns empty array when no bindings are registered", () => {
    const registry = new HotkeyRegistry();

    function BindingsReader({ onRead }: { onRead: (b: readonly unknown[]) => void }) {
      const bindings = useHotkeyBindings(registry);
      onRead(bindings);
      return null;
    }

    const onRead = vi.fn();
    render(
      <HotkeyProvider registry={registry}>
        <BindingsReader onRead={onRead} />
      </HotkeyProvider>,
    );

    const lastCall = onRead.mock.calls[onRead.mock.calls.length - 1];
    expect(lastCall[0]).toHaveLength(0);
  });

  it("reflects newly registered bindings without re-mounting", async () => {
    const registry = new HotkeyRegistry();
    const recorded: number[] = [];

    function BindingsWatcher() {
      const bindings = useHotkeyBindings(registry);
      recorded.push(bindings.length);
      return <div data-testid="count" data-count={bindings.length} />;
    }

    render(
      <HotkeyProvider registry={registry}>
        <BindingsWatcher />
      </HotkeyProvider>,
    );

    // Register a new binding — should trigger a re-render via useSyncExternalStore
    await act(async () => {
      registry.register({
        id: "test.binding",
        chord: "x",
        scope: "global",
        group: "Navigation",
        label: "Test",
        handler: vi.fn(),
      });
    });

    const el = document.querySelector("[data-testid='count']");
    expect(el?.getAttribute("data-count")).toBe("1");
  });
});
