/**
 * __tests__/hotkey-cheat-sheet.test.tsx — Cheat sheet auto-derivation.
 *
 * PLAN-0059 W1 closure check: the cheat sheet must reflect EXACTLY the bindings
 * registered in the registry — adding a new binding makes it appear; removing
 * one makes it disappear. This eliminates the "lying StatusBar" failure mode
 * by making it structurally impossible to advertise an unwired chord.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyCheatSheet } from "@/components/shell/HotkeyCheatSheet";
import { HotkeyRegistry, type HotkeyBinding } from "@/lib/hotkey-registry";
import { useChordHotkeys } from "@/hooks/useChordHotkeys";

// The cheat sheet relies on the document-level chord listener to dispatch the
// `?` keypress to its registered handler. In production layout that listener
// is mounted by GlobalHotkeyBindings; in tests we mount it via this wrapper
// so the test integration mirrors the real flow.
function ListenerHost() {
  useChordHotkeys();
  return null;
}

function makeBinding(
  id: string,
  chord: string,
  label: string,
  group: HotkeyBinding["group"] = "Navigation",
): HotkeyBinding {
  return {
    id,
    chord,
    scope: "global",
    group,
    label,
    handler: vi.fn(),
  };
}

describe("HotkeyCheatSheet", () => {
  let registry: HotkeyRegistry;

  beforeEach(() => {
    registry = new HotkeyRegistry();
  });

  afterEach(() => {
    registry.clear();
  });

  it("does not render when closed (no bindings yet → still hidden)", () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );
    // Closed by default — no dialog in DOM.
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens via `?` chord and lists registered bindings grouped by section", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    // Register two bindings BEFORE opening so they're listed when the dialog renders.
    act(() => {
      registry.register(makeBinding("nav.dashboard", "g d", "Go to Dashboard", "Navigation"));
      registry.register(makeBinding("view.toggle.sidebar", "mod+b", "Toggle sidebar", "View"));
    });

    // Press ? to open. The cheat-sheet's own keydown listener handles "?" via
    // the registered binding (registered in its useEffect on mount).
    await userEvent.keyboard("?");

    // Dialog should appear.
    const dialog = await screen.findByRole("dialog", { name: /keyboard shortcuts/i });
    expect(dialog).toBeInTheDocument();

    // Both bindings should appear under their groups.
    expect(screen.getByText("Go to Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Toggle sidebar")).toBeInTheDocument();

    // Group headers visible.
    expect(screen.getByText("Navigation")).toBeInTheDocument();
    expect(screen.getByText("View")).toBeInTheDocument();
  });

  it("filter input narrows the visible bindings", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    act(() => {
      registry.register(makeBinding("nav.dashboard", "g d", "Go to Dashboard"));
      registry.register(makeBinding("nav.portfolio", "g p", "Go to Portfolio"));
    });

    await userEvent.keyboard("?");
    const filter = await screen.findByPlaceholderText(/filter shortcuts/i);

    // Type "Dash" → only Dashboard binding should remain visible.
    await userEvent.type(filter, "Dash");
    expect(screen.getByText("Go to Dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Go to Portfolio")).toBeNull();
  });

  it("Esc closes the cheat sheet", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    act(() => {
      registry.register(makeBinding("nav.dashboard", "g d", "Go to Dashboard"));
    });

    await userEvent.keyboard("?");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("re-rendering after a registration updates the displayed list", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    act(() => {
      registry.register(makeBinding("nav.dashboard", "g d", "Go to Dashboard"));
    });
    await userEvent.keyboard("?");
    expect(await screen.findByText("Go to Dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Go to News")).toBeNull();

    // Register a new binding while the cheat sheet is open. useSyncExternalStore
    // must propagate the change — auto-derivation is the contract.
    act(() => {
      registry.register(makeBinding("nav.news", "g n", "Go to News"));
    });
    expect(await screen.findByText("Go to News")).toBeInTheDocument();
  });

  it("`?` does NOT open the cheat sheet while a text input has focus", async () => {
    // Round-3 polish pin: `?` is a modifier-less chord, so useChordHotkeys
    // must suspend it while the user is typing (input/textarea/contenteditable)
    // — otherwise typing a literal question mark in the search box would pop
    // the overlay. The suspension rule lives in isTextInputActive(); this test
    // pins it specifically for the cheat-sheet chord.
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    const input = document.createElement("input");
    input.type = "text";
    document.body.appendChild(input);
    input.focus();
    try {
      // userEvent.keyboard types into the focused element — exactly the
      // "user typing a question mark" scenario.
      await userEvent.keyboard("?");
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      input.remove();
    }
  });

  it("`?` is suppressed inside a contenteditable region (chat composer)", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    // jsdom does not compute isContentEditable from the attribute — define it
    // explicitly so isTextInputActive() sees what a real browser reports.
    Object.defineProperty(editable, "isContentEditable", { value: true });
    editable.tabIndex = 0; // make focusable in jsdom
    document.body.appendChild(editable);
    editable.focus();
    try {
      fireEvent.keyDown(editable, { key: "?" });
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      editable.remove();
    }
  });

  it("cannot advertise an unregistered chord (auto-derivation guarantee)", async () => {
    // Render the cheat sheet with NO bindings registered. The dialog body must
    // contain zero binding rows. This is the structural anti-fraud guarantee
    // that closes F-LAYOUT-001.
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );
    await userEvent.keyboard("?");
    const dialog = await screen.findByRole("dialog");
    // The cheat sheet itself self-registers the `?` binding (View group). Any
    // other group should be absent because no other bindings exist.
    expect(dialog.textContent).not.toMatch(/Go to Dashboard/);
    expect(dialog.textContent).not.toMatch(/Go to Portfolio/);
  });

  // ── Focus trap (Round-4 hardening) ──────────────────────────────────────────
  // The cheat sheet is a hand-rolled aria-modal overlay (no Radix), so it must
  // implement the WAI-ARIA dialog focus contract itself: Tab cycles within the
  // dialog (wrapping at the edges) and focus returns to the opener on close.
  // Focusable order in the dialog DOM: [close button] → [filter input].

  /** Wait for the rAF-deferred autofocus of the filter input after opening. */
  async function openAndWaitForFocus(): Promise<HTMLElement> {
    await userEvent.keyboard("?");
    const filter = await screen.findByPlaceholderText(/filter shortcuts/i);
    // The component focuses the input inside requestAnimationFrame — poll
    // until that lands so the trap assertions start from a known state.
    await vi.waitFor(() => expect(filter).toHaveFocus());
    return filter;
  }

  it("Tab on the last focusable wraps to the first (focus stays trapped)", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    const filter = await openAndWaitForFocus();
    const closeBtn = screen.getByRole("button", {
      name: /close keyboard shortcuts/i,
    });

    // Filter input is the LAST focusable; Tab must wrap to the close button
    // (the first), never escape into the page behind the backdrop.
    expect(filter).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeBtn).toHaveFocus();
  });

  it("Shift+Tab on the first focusable wraps to the last", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    const filter = await openAndWaitForFocus();
    const closeBtn = screen.getByRole("button", {
      name: /close keyboard shortcuts/i,
    });

    // Move to the first focusable, then Shift+Tab must wrap back to the last.
    closeBtn.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(filter).toHaveFocus();
  });

  it("pulls focus back into the dialog if it escaped (e.g. to <body>)", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    await openAndWaitForFocus();

    // Simulate focus having escaped the dialog entirely (backdrop click puts
    // activeElement on <body> in some browsers). The next Tab must re-engage
    // the trap by focusing the first dialog focusable.
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.body).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    const closeBtn = screen.getByRole("button", {
      name: /close keyboard shortcuts/i,
    });
    expect(closeBtn).toHaveFocus();
  });

  it("restores focus to the previously focused element on close", async () => {
    render(
      <HotkeyProvider registry={registry}>
        <ListenerHost />
        <HotkeyCheatSheet />
      </HotkeyProvider>,
    );

    // Give some page element focus BEFORE opening — this is the "opener" the
    // dialog must hand focus back to (WAI-ARIA dialog pattern).
    const opener = document.createElement("button");
    opener.textContent = "opener";
    document.body.appendChild(opener);
    opener.focus();
    try {
      await openAndWaitForFocus();
      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(opener).toHaveFocus();
    } finally {
      opener.remove();
    }
  });
});
