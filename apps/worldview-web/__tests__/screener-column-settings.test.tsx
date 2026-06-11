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
  ESSENTIAL_COLUMN_KEYS,
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
    // WHY not every(visible): PLAN-0092 Wave C added 3 opt-in columns
    // (opMargin, evEbitda, avgVol); PRD-0089 fh-column-count-cap demoted
    // forwardPe to opt-in to satisfy the §6.3 14-column cap; Wave-2
    // (2026-06-10) demoted score to opt-in (market_impact_score has no
    // backend data source — permanently "—"). The 13 default-visible
    // columns below are the canonical set.
    const defaultVisibleKeys = ["ticker", "name", "sector", "price", "change",
      "marketCap", "pe", "revenueGrowth", "divYield", "roe",
      "beta", "range52w", "sparkline"];
    const defaultVisible = cols.filter((c) => defaultVisibleKeys.includes(c.key));
    expect(defaultVisible.every((c) => c.visible)).toBe(true);
    // Opt-in columns should be hidden by default (forwardPe demoted per §6.3
    // cap; score demoted in Wave-2 — no data source)
    const optInKeys = ["opMargin", "evEbitda", "avgVol", "forwardPe", "score"];
    const optIn = cols.filter((c) => optInKeys.includes(c.key));
    expect(optIn.every((c) => !c.visible)).toBe(true);
  });

  it("saveColumnPrefs + loadColumnPrefs round-trips visibility", () => {
    // Round 2: ticker (index 0) became non-hideable, so the round-trip is
    // asserted on a hideable column (sector) — same assertion strength,
    // different subject. Pinned-column coercion has its own test below.
    const cols = makeCols();
    const sectorIdx = cols.findIndex((c) => c.key === "sector");
    cols[sectorIdx].visible = false;
    saveColumnPrefs(cols);
    const loaded = loadColumnPrefs();
    expect(loaded.find((c) => c.key === "sector")?.visible).toBe(false);
  });

  it("loadColumnPrefs coerces essential columns (ticker, name) visible even when stored hidden", () => {
    // Round 2 regression guard: prefs persisted BEFORE the pinned-column rule
    // existed may carry visible:false for ticker/name. The read path must
    // heal them — a screener without its identity columns is unusable.
    const cols = makeCols();
    for (const c of cols) {
      if (ESSENTIAL_COLUMN_KEYS.includes(c.key)) c.visible = false;
    }
    saveColumnPrefs(cols);
    const loaded = loadColumnPrefs();
    expect(loaded.find((c) => c.key === "ticker")?.visible).toBe(true);
    expect(loaded.find((c) => c.key === "name")?.visible).toBe(true);
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
    // Round 2: Ticker is now PINNED (non-hideable), so the toggle behaviour
    // is asserted on Sector — the first hideable column. Same assertion
    // strength (onChange fired with flipped visibility), different subject.
    const sectorToggle = await screen.findByLabelText(/toggle sector column visibility/i);
    await user.click(sectorToggle);
    expect(onChange).toHaveBeenCalled();
    const next = onChange.mock.calls[0][0] as ScreenerColumn[];
    expect(next.find((c) => c.key === "sector")?.visible).toBe(false);
  });

  it("essential columns (ticker, name) render disabled checkboxes that cannot toggle", async () => {
    // Round 2: ticker/name are the row identity — hiding them makes every
    // other cell context-free numbers, so the popover pins them on.
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ColumnSettingsPopover columns={makeCols()} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: /configure columns/i }));

    const tickerToggle = await screen.findByLabelText(/toggle ticker column visibility/i);
    const nameToggle = await screen.findByLabelText(/toggle name column visibility/i);
    expect(tickerToggle).toBeDisabled();
    expect(nameToggle).toBeDisabled();

    // Clicking a disabled checkbox must be a no-op — no onChange, no persist.
    await user.click(tickerToggle);
    expect(onChange).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(SCREENER_COLUMNS_KEY)).toBeNull();
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
