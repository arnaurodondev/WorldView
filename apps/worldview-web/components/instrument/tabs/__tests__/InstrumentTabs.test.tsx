/**
 * components/instrument/tabs/__tests__/InstrumentTabs.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): InstrumentTabs collapses the 4-tab
 * predecessor into 3 tabs (Quote / Financials / Intelligence) with Q/F/I
 * mnemonic chords. This test pins three contracts:
 *
 *   1. Clicking each tab button calls onTabChange with the right key.
 *   2. Pressing the chord key fires onTabChange with the matching tab.
 *   3. Chords MUST be suspended while a text input is focused — pressing
 *      "q" inside a search box should not switch the tab.
 *
 * WHY full HotkeyProvider + useChordHotkeys (and not a unit-level stub):
 * The whole point of the integration is that InstrumentTabs registers via
 * <HotkeyScope> and the document listener routes the keydown through the
 * registry. Stubbing the registry would miss the input-suspension behaviour
 * that lives in useChordHotkeys' isTextInputActive() guard.
 *
 * WHY initialScopes=["global", "page"]: <HotkeyScope> normally pushes "page"
 * on mount, but pushScope is async-ish (effect-driven). Pre-seeding the
 * scope set avoids a race between mount and fireEvent.keyDown.
 *
 * Reference pattern: __tests__/instrument-hotkeys.test.tsx — same author's
 * Bloomberg mnemonic suite uses identical scaffolding for the legacy
 * D/F/N/I chords.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import { InstrumentTabs } from "@/components/instrument/tabs/InstrumentTabs";

// ── next/navigation mock ──────────────────────────────────────────────────────
// WHY: useChordHotkeys reads usePathname() for page-scoped binding resolution.
// InstrumentTabs binds at page="/instruments/", so we mock a matching path.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY a tiny host: useChordHotkeys is a hook, not a component — wrap it.
function ListenerHost() {
  useChordHotkeys();
  return null;
}

describe("InstrumentTabs", () => {
  let registry: HotkeyRegistry;

  beforeEach(() => {
    // WHY fresh registry per test: chord bindings persist on the singleton
    // across tests otherwise; a stale "quote → onTabChange A" would fire
    // when test B does keyDown("q").
    registry = new HotkeyRegistry();
  });

  afterEach(() => {
    registry.clear();
  });

  it("renders 3 tab buttons with QUOTE / FINANCIALS / INTELLIGENCE labels", () => {
    const onTabChange = vi.fn();
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <InstrumentTabs activeTab="quote" onTabChange={onTabChange} />
      </HotkeyProvider>,
    );
    // WHY explicit labels: PRD-0088 §6.6 spec — these three labels are the
    // public contract; a future rename ("INTEL" → "INTELLIGENCE") would
    // surface here.
    expect(screen.getByRole("button", { name: "QUOTE" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "FINANCIALS" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "INTELLIGENCE" })).toBeInTheDocument();
  });

  it("marks the active tab with aria-current=page", () => {
    const onTabChange = vi.fn();
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <InstrumentTabs activeTab="financials" onTabChange={onTabChange} />
      </HotkeyProvider>,
    );
    // Only one tab should carry aria-current; this is the a11y signal screen
    // readers use to announce "current page".
    expect(screen.getByRole("button", { name: "FINANCIALS" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "QUOTE" })).not.toHaveAttribute("aria-current");
  });

  // ── Hotkey behaviour ──────────────────────────────────────────────────────

  it.each([
    ["q", "quote"],
    ["f", "financials"],
    ["i", "intelligence"],
  ])("pressing %s switches to tab %s", (key, expectedTab) => {
    const onTabChange = vi.fn();
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <ListenerHost />
        <InstrumentTabs activeTab="quote" onTabChange={onTabChange} />
      </HotkeyProvider>,
    );
    // WHY fireEvent.keyDown on document: the chord listener attaches at the
    // document level (capture phase) — not on any specific DOM element.
    fireEvent.keyDown(document, { key });
    expect(onTabChange).toHaveBeenCalledWith(expectedTab);
  });

  it("does NOT fire Q/F/I chords inside a text input (typing-suspension guard)", () => {
    // WHY this matters: a single-letter mnemonic that fired while the user
    // types "quarterly" in a search box would corrupt every search; the
    // listener's isTextInputActive() guard is what prevents that.
    const onTabChange = vi.fn();
    const { container } = render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <ListenerHost />
        <InstrumentTabs activeTab="quote" onTabChange={onTabChange} />
        <input type="text" data-testid="search" />
      </HotkeyProvider>,
    );
    const input = container.querySelector("[data-testid='search']") as HTMLInputElement;
    input.focus();
    // Press each chord inside the input — none should fire.
    fireEvent.keyDown(input, { key: "q" });
    fireEvent.keyDown(input, { key: "f" });
    fireEvent.keyDown(input, { key: "i" });
    expect(onTabChange).not.toHaveBeenCalled();
  });

  // ── Round-4 hardening (item 2): roving tabindex + arrow-key navigation ────

  it("gives only the active tab tabIndex=0 (roving tabindex)", () => {
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <InstrumentTabs activeTab="financials" onTabChange={vi.fn()} />
      </HotkeyProvider>,
    );
    // One Tab-stop for the whole strip: the active tab is focusable, the
    // others are reached with arrows (WAI-ARIA composite-widget contract).
    expect(screen.getByRole("button", { name: "FINANCIALS" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("button", { name: "QUOTE" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("button", { name: "INTELLIGENCE" })).toHaveAttribute("tabindex", "-1");
  });

  it.each([
    // [start tab, key, expected target]
    ["quote", "ArrowRight", "financials"],
    ["financials", "ArrowRight", "intelligence"],
    ["intelligence", "ArrowRight", "quote"], // wrap-around
    ["quote", "ArrowLeft", "intelligence"], // wrap-around
    ["intelligence", "Home", "quote"],
    ["quote", "End", "intelligence"],
  ] as const)(
    "from %s, %s selects %s and moves focus there",
    (startTab, key, expectedTab) => {
      const onTabChange = vi.fn();
      render(
        <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
          <InstrumentTabs activeTab={startTab} onTabChange={onTabChange} />
        </HotkeyProvider>,
      );
      const labels: Record<string, string> = {
        quote: "QUOTE",
        financials: "FINANCIALS",
        intelligence: "INTELLIGENCE",
      };
      const startBtn = screen.getByRole("button", { name: labels[startTab] });
      startBtn.focus();
      fireEvent.keyDown(startBtn, { key });
      expect(onTabChange).toHaveBeenCalledWith(expectedTab);
      // Focus follows selection — the focus ring must land on the new tab.
      expect(screen.getByRole("button", { name: labels[expectedTab] })).toHaveFocus();
    },
  );

  it("ignores unrelated keys (no accidental tab switches)", () => {
    const onTabChange = vi.fn();
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <InstrumentTabs activeTab="quote" onTabChange={onTabChange} />
      </HotkeyProvider>,
    );
    const btn = screen.getByRole("button", { name: "QUOTE" });
    fireEvent.keyDown(btn, { key: "ArrowDown" });
    fireEvent.keyDown(btn, { key: "a" });
    expect(onTabChange).not.toHaveBeenCalled();
  });

  it("clicking a tab button calls onTabChange with the correct key", () => {
    const onTabChange = vi.fn();
    render(
      <HotkeyProvider registry={registry} initialScopes={["global", "page"]}>
        <InstrumentTabs activeTab="quote" onTabChange={onTabChange} />
      </HotkeyProvider>,
    );
    // WHY: redundant with hotkey path, but click is the primary input — a
    // regression that breaks onClick (e.g. wrong binding closure) must fail.
    fireEvent.click(screen.getByRole("button", { name: "INTELLIGENCE" }));
    expect(onTabChange).toHaveBeenCalledWith("intelligence");
  });
});
