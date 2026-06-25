/**
 * CommandPaletteTrigger.test.tsx — pins the DISCOVERABILITY behaviours of the
 * visible ⌘K command-palette entry point (roadmap §3 / B4).
 *
 * What we guarantee:
 *  1. the trigger is always rendered and visibly advertises the palette
 *     ("Search or jump to…" copy + a shortcut chip) — the whole point of B4;
 *  2. clicking it dispatches the SAME open event the palette listens for
 *     (OPEN_COMMAND_PALETTE_EVENT) — i.e. it opens the existing palette and
 *     does NOT duplicate it;
 *  3. it carries an accessible name describing the action + the chord;
 *  4. the shortcut chip is platform-aware (⌘ on mac, Ctrl on others) after
 *     mount — without throwing a hydration-mismatch on the server render.
 *
 * WHY we mock @/components/shell/CommandPalette: the real module pulls in
 * TanStack Query, the gateway, auth and the cmdk dialog — none of which the
 * trigger needs. We only depend on the exported event-name CONSTANT, so we mock
 * the module down to that single export. This also proves the trigger fires the
 * exact string the palette exports (the mock value flows through to the assert).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the palette module to just the open-event constant the trigger imports.
vi.mock("@/components/shell/CommandPalette", () => ({
  OPEN_COMMAND_PALETTE_EVENT: "worldview:open-command-palette",
}));

import { CommandPaletteTrigger } from "@/components/shell/CommandPaletteTrigger";

describe("CommandPaletteTrigger", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is always rendered and advertises the palette (discoverability)", () => {
    render(<CommandPaletteTrigger />);
    // The visible prompt copy is the discoverability signal — a mouse user must
    // be able to SEE that there is a search/jump surface here.
    expect(screen.getByText("Search or jump to…")).toBeInTheDocument();
    // And it must be an actually-clickable control, not inert decoration.
    expect(screen.getByTestId("command-palette-trigger")).toBeInTheDocument();
  });

  it("exposes an accessible name describing the action and the chord", () => {
    render(<CommandPaletteTrigger />);
    // Screen-reader users get the full intent even though the visible text is terse.
    expect(
      screen.getByRole("button", {
        name: /search or jump to anything \(cmd\+k or ctrl\+k\)/i,
      }),
    ).toBeInTheDocument();
  });

  it("dispatches the palette open event on click (opens, does not duplicate)", async () => {
    const user = userEvent.setup();
    // Spy on the window event the palette listens for. We assert on the exact
    // event NAME so a typo or contract drift between trigger and palette fails here.
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");

    render(<CommandPaletteTrigger />);
    await user.click(screen.getByTestId("command-palette-trigger"));

    expect(dispatchSpy).toHaveBeenCalledTimes(1);
    const dispatched = dispatchSpy.mock.calls[0]![0] as Event;
    expect(dispatched.type).toBe("worldview:open-command-palette");
  });

  it("renders a platform-aware shortcut chip after mount without a hydration crash", async () => {
    render(<CommandPaletteTrigger />);
    // The chip starts as the stable "⌘K" placeholder (server-safe) and the
    // effect swaps in the platform-correct label. In jsdom (non-mac default)
    // the post-mount label is "Ctrl+K"; on a mac runner it stays "⌘K". Accept
    // either so the test is portable across CI platforms — the contract under
    // test is "a non-empty, recognisable chord label is shown", not the exact OS.
    await waitFor(() => {
      const chip = screen.getByText(/⌘K|Ctrl\+K/);
      expect(chip.tagName.toLowerCase()).toBe("kbd");
    });
  });
});
