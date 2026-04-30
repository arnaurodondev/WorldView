/**
 * __tests__/instrument-hotkeys.test.tsx — Bloomberg mnemonic chord tests.
 *
 * WHY THIS EXISTS: PLAN-0059 W1 adds single-letter mnemonics on the instrument
 * detail page (D=DES, F=FA, N=CN, I=Intel). This test closes F-QA-002 (BLOCKING)
 * from the 2026-04-30 QA report by verifying the chord → tab change contract.
 *
 * SCOPE: These tests verify the hotkey infrastructure end-to-end for page-scoped
 * bindings — they do NOT render the full instrument page (too many dependencies).
 * Instead they register the bindings directly in a fresh registry and assert that
 * the listener dispatches correctly given the correct pathname.
 *
 * WHY page-scope via initialScopes (not <HotkeyScope>): <HotkeyScope> also calls
 * pushScope which requires HotkeyProvider to be set up. Using initialScopes lets
 * us declare the test's scope state without mounting an extra component.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Navigation mock ───────────────────────────────────────────────────────────
// WHY: useChordHotkeys reads usePathname() to resolve page-scoped bindings.
// The instrument page path is what the HotkeyScope sets as page="/instruments/".
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// ── Listener host ─────────────────────────────────────────────────────────────

function ListenerHost() {
  useChordHotkeys();
  return null;
}

// ── Bloomberg mnemonics ───────────────────────────────────────────────────────

const MNEMONICS: Array<{ key: string; tab: string; label: string }> = [
  { key: "d", tab: "overview",       label: "DES — Overview" },
  { key: "f", tab: "fundamentals",   label: "FA — Fundamentals" },
  { key: "n", tab: "news",           label: "CN — News" },
  { key: "i", tab: "intelligence",   label: "Intelligence" },
];

describe("Instrument page Bloomberg mnemonics (PLAN-0059 W1)", () => {
  let registry: HotkeyRegistry;

  beforeEach(() => {
    registry = new HotkeyRegistry();
  });

  afterEach(() => {
    registry.clear();
  });

  // ── Happy path: each mnemonic fires its tab ────────────────────────────────

  for (const { key, tab, label } of MNEMONICS) {
    it(`pressing "${key.toUpperCase()}" calls onTabChange("${tab}") — ${label}`, () => {
      const onTabChange = vi.fn();

      // Register exactly as InstrumentMnemonicHotkeys does it via <HotkeyScope>
      registry.register({
        id: `ins.tab.${tab}`,
        chord: key,
        scope: "page",
        page: "/instruments/",
        group: "Symbol",
        label,
        handler: () => onTabChange(tab),
      });

      render(
        // initialScopes mirrors what HotkeyScope pushes: "page" + the base "global"
        <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
          <ListenerHost />
        </HotkeyProvider>,
      );

      fireEvent.keyDown(document, { key });
      expect(onTabChange).toHaveBeenCalledWith(tab);
    });
  }

  // ── Modal guard: mnemonics must NOT fire when a dialog is open ────────────

  it("does NOT fire instrument mnemonics when modal scope is active", () => {
    // This replicates the bug guard from the layout audit: pressing a single-
    // letter key inside a confirmation dialog must not switch the active tab
    // behind the dialog.
    const onTabChange = vi.fn();

    registry.register({
      id: "ins.tab.overview",
      chord: "d",
      scope: "page",
      page: "/instruments/",
      group: "Symbol",
      label: "DES — Overview",
      handler: () => onTabChange("overview"),
    });

    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page", "modal"]}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "d" });
    expect(onTabChange).not.toHaveBeenCalled();
  });

  // ── Page-guard: page-scoped binding with mismatched page must NOT fire ────

  it("does NOT fire when the binding page does not match current pathname", () => {
    // The mock pathname is "/instruments/ent-001". A binding scoped to
    // "/screener/" must NOT fire on this page — verifies matchesPage().
    const onTabChange = vi.fn();

    registry.register({
      id: "ins.tab.overview.wrong-page",
      chord: "d",
      scope: "page",
      page: "/screener/",  // mismatch — current pathname is /instruments/...
      group: "Symbol",
      label: "DES — Overview",
      handler: () => onTabChange("overview"),
    });

    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <ListenerHost />
      </HotkeyProvider>,
    );

    fireEvent.keyDown(document, { key: "d" });
    expect(onTabChange).not.toHaveBeenCalled();
  });

  // ── Suspension inside inputs: mnemonics must not swallow typed letters ────

  it("suspends mnemonic chords inside a text input", () => {
    const onTabChange = vi.fn();

    registry.register({
      id: "ins.tab.fundamentals",
      chord: "f",
      scope: "page",
      page: "/instruments/",
      group: "Symbol",
      label: "FA — Fundamentals",
      handler: () => onTabChange("fundamentals"),
    });

    const { container } = render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <ListenerHost />
        <input type="text" data-testid="search" />
      </HotkeyProvider>,
    );

    const input = container.querySelector("[data-testid='search']") as HTMLInputElement;
    input.focus();
    // Pressing "f" inside a text input must not switch to Fundamentals tab
    fireEvent.keyDown(input, { key: "f" });
    expect(onTabChange).not.toHaveBeenCalled();
  });
});
