/**
 * __tests__/screener-column-settings.test.tsx — visibility toggle, reset, persistence.
 *
 * WHY THIS EXISTS: column customization is the user's main lever for shaping
 * the screener density. These tests cover toggle, reset-to-defaults, and
 * localStorage persistence — the three behaviours that affect what every other
 * row in the table renders.
 *
 * Note: drag-reorder relies on HTML5 DnD events that jsdom doesn't fire
 * realistically; we test the underlying lib (loadColumnPrefs / saveColumnPrefs)
 * instead and let Playwright cover the actual drag interaction in the e2e suite.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ColumnSettingsPopover } from "@/components/screener/ColumnSettingsPopover";
import {
  DEFAULT_COLUMNS,
  loadColumnPrefs,
  saveColumnPrefs,
  resetColumnPrefs,
  SCREENER_COLUMNS_KEY,
  type ScreenerColumn,
} from "@/lib/screener-columns";

function makeCols(): ScreenerColumn[] {
  return DEFAULT_COLUMNS.map((c) => ({ ...c }));
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("screener-columns lib — load / save / reset", () => {
  it("loadColumnPrefs returns defaults when localStorage is empty", () => {
    const cols = loadColumnPrefs();
    expect(cols.length).toBe(DEFAULT_COLUMNS.length);
    expect(cols.every((c) => c.visible)).toBe(true);
  });

  it("saveColumnPrefs + loadColumnPrefs round-trips visibility", () => {
    const cols = makeCols();
    cols[0].visible = false;
    saveColumnPrefs(cols);
    const loaded = loadColumnPrefs();
    expect(loaded[0].visible).toBe(false);
  });

  it("loadColumnPrefs preserves user-saved order", () => {
    const cols = makeCols();
    // Move "score" to the front.
    const scoreIdx = cols.findIndex((c) => c.key === "score");
    const [score] = cols.splice(scoreIdx, 1);
    cols.unshift(score);
    saveColumnPrefs(cols);
    const loaded = loadColumnPrefs();
    expect(loaded[0].key).toBe("score");
  });

  it("resetColumnPrefs clears localStorage and returns defaults", () => {
    const cols = makeCols();
    cols[0].visible = false;
    saveColumnPrefs(cols);
    const fresh = resetColumnPrefs();
    expect(fresh[0].visible).toBe(true);
    expect(window.localStorage.getItem(SCREENER_COLUMNS_KEY)).toBeNull();
  });

  it("loadColumnPrefs degrades to defaults on malformed localStorage", () => {
    window.localStorage.setItem(SCREENER_COLUMNS_KEY, "not-json");
    expect(loadColumnPrefs().length).toBe(DEFAULT_COLUMNS.length);
  });

  it("loadColumnPrefs appends NEW default columns that the user has never seen", () => {
    // Simulate a stored pref that's missing the sparkline column entirely.
    const partial = DEFAULT_COLUMNS
      .filter((c) => c.key !== "sparkline")
      .map((c) => ({ key: c.key, visible: c.visible }));
    window.localStorage.setItem(SCREENER_COLUMNS_KEY, JSON.stringify(partial));
    const loaded = loadColumnPrefs();
    expect(loaded.find((c) => c.key === "sparkline")).toBeDefined();
  });

  it("loadColumnPrefs drops stored entries whose key is no longer in defaults", () => {
    window.localStorage.setItem(
      SCREENER_COLUMNS_KEY,
      JSON.stringify([{ key: "ghost", visible: true }, { key: "ticker", visible: true }]),
    );
    const loaded = loadColumnPrefs();
    expect(loaded.find((c) => c.key === "ghost")).toBeUndefined();
    expect(loaded.find((c) => c.key === "ticker")).toBeDefined();
  });
});

describe("ColumnSettingsPopover — UI", () => {
  it("opens the popover and renders one checkbox per column", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ColumnSettingsPopover columns={makeCols()} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: /configure columns/i }));
    // Each column has a checkbox aria-label "Toggle <Label> column visibility".
    const checkboxes = await screen.findAllByRole("checkbox");
    expect(checkboxes.length).toBe(DEFAULT_COLUMNS.length);
  });

  it("toggling a checkbox calls onChange with the new visibility", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ColumnSettingsPopover columns={makeCols()} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: /configure columns/i }));
    // Toggle the first column (Ticker).
    const tickerToggle = await screen.findByLabelText(/toggle ticker column visibility/i);
    await user.click(tickerToggle);
    expect(onChange).toHaveBeenCalled();
    const next = onChange.mock.calls[0][0] as ScreenerColumn[];
    expect(next.find((c) => c.key === "ticker")?.visible).toBe(false);
  });

  it("Reset button restores defaults and clears localStorage", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Pre-populate with a non-default state.
    const customised = makeCols();
    customised[0].visible = false;
    saveColumnPrefs(customised);
    render(<ColumnSettingsPopover columns={customised} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: /configure columns/i }));
    await user.click(await screen.findByRole("button", { name: /reset columns to default/i }));
    expect(onChange).toHaveBeenCalled();
    const fresh = onChange.mock.calls[0][0] as ScreenerColumn[];
    expect(fresh[0].visible).toBe(true);
    expect(window.localStorage.getItem(SCREENER_COLUMNS_KEY)).toBeNull();
  });
});
