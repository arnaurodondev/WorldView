/**
 * __tests__/screener-saved-screens.test.tsx — UI tests for SavedScreensDialog
 *
 * WHY THIS EXISTS: The dialog is the only path users have to save / load /
 * delete their screens. These tests cover the happy path (save → list → load
 * → delete) plus the empty state.
 *
 * WHY MOCK window.confirm: deletion shows a confirm prompt; jsdom auto-accepts
 * window.confirm but Vitest defaults to false. Mocking it to return true lets
 * us exercise the delete path; mocking false lets us assert "user cancelled".
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SavedScreensDialog } from "@/components/screener/SavedScreensDialog";
import type { FilterState } from "@/components/screener/ScreenerFilterBar";
import * as savedScreensLib from "@/lib/saved-screens";

const MOCK_FILTERS: FilterState = { search: "", sector: "", capTier: "ALL" };

function setup(overrides: Partial<React.ComponentProps<typeof SavedScreensDialog>> = {}) {
  const onLoad = vi.fn();
  const onSaved = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <SavedScreensDialog
      open
      onOpenChange={onOpenChange}
      currentFilters={MOCK_FILTERS}
      onLoad={onLoad}
      onSaved={onSaved}
      {...overrides}
    />,
  );
  return { onLoad, onSaved, onOpenChange };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("SavedScreensDialog — Save tab", () => {
  it("renders the Save tab by default with a name input", () => {
    setup();
    expect(screen.getByLabelText(/saved screen name/i)).toBeInTheDocument();
  });

  it("Save button is disabled when name is empty", () => {
    setup();
    const btn = screen.getByRole("button", { name: /save current filter set/i });
    expect(btn).toBeDisabled();
  });

  it("typing a name enables the Save button and clicking it persists the screen", async () => {
    const user = userEvent.setup();
    const { onSaved } = setup();
    const input = screen.getByLabelText(/saved screen name/i);
    await user.type(input, "My Tech Screen");
    const btn = screen.getByRole("button", { name: /save current filter set/i });
    expect(btn).not.toBeDisabled();
    await user.click(btn);
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(savedScreensLib.listSavedScreens().length).toBe(1);
    expect(savedScreensLib.listSavedScreens()[0].name).toBe("My Tech Screen");
  });
});

describe("SavedScreensDialog — Load tab", () => {
  it("shows the empty-state message when no screens are saved", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("tab", { name: /load screen/i }));
    expect(screen.getByText(/no saved screens yet/i)).toBeInTheDocument();
  });

  it("lists saved screens with a Load button each", async () => {
    savedScreensLib.saveScreen("Tech Screen", MOCK_FILTERS);
    savedScreensLib.saveScreen("Energy Screen", MOCK_FILTERS);
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("tab", { name: /load screen/i }));
    expect(screen.getByText("Tech Screen")).toBeInTheDocument();
    expect(screen.getByText("Energy Screen")).toBeInTheDocument();
    // Two Load buttons (one per row)
    expect(screen.getAllByRole("button", { name: /load screen .+/i }).length).toBe(2);
  });

  it("clicking Load fires onLoad with the saved filters and closes the dialog", async () => {
    const customFilters: FilterState = { search: "TSLA", sector: "", capTier: "MID" };
    savedScreensLib.saveScreen("Tesla watch", customFilters);
    const user = userEvent.setup();
    const { onLoad, onOpenChange } = setup();
    await user.click(screen.getByRole("tab", { name: /load screen/i }));
    await user.click(screen.getByRole("button", { name: /load screen tesla watch/i }));
    expect(onLoad).toHaveBeenCalledWith(customFilters);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("clicking Delete with confirmed prompt removes the screen", async () => {
    savedScreensLib.saveScreen("Doomed", MOCK_FILTERS);
    // WHY mock confirm true: simulates the user accepting the delete prompt.
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("tab", { name: /load screen/i }));
    await user.click(screen.getByRole("button", { name: /delete screen doomed/i }));
    expect(savedScreensLib.listSavedScreens().length).toBe(0);
  });

  it("clicking Delete with cancelled prompt keeps the screen", async () => {
    savedScreensLib.saveScreen("Survivor", MOCK_FILTERS);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("tab", { name: /load screen/i }));
    await user.click(screen.getByRole("button", { name: /delete screen survivor/i }));
    expect(savedScreensLib.listSavedScreens().length).toBe(1);
  });
});
