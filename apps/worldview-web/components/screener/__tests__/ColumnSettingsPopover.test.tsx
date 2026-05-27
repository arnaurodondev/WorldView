/**
 * components/screener/__tests__/ColumnSettingsPopover.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: T-IA-08 added the 14-column warning footer (muted when ≤14 visible,
 * warning-tinted when >14). The threshold is the only place in the UI
 * that protects the 1440px viewport contract from accidental overflow.
 * Pin both states so a future refactor cannot drop the warning silently.
 *
 * NOTE: there is also a legacy `__tests__/screener-column-settings.test.tsx`
 * that covers visibility toggle / reset / persistence. This file focuses
 * narrowly on the warning footer copy + colour escalation introduced by
 * T-IA-08 so the new behaviour gets its own regression surface.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ColumnSettingsPopover } from "@/components/screener/ColumnSettingsPopover";
import { DEFAULT_COLUMNS, type ScreenerColumn } from "@/lib/screener-columns";

/**
 * Build a column list with exactly N visible entries. WHY: the popover
 * compares `columns.filter(c => c.visible).length > 14` against the
 * threshold; we need controllable visibility counts to exercise both
 * sides of the predicate without coupling to the DEFAULT_COLUMNS shape.
 */
function colsWithVisibleCount(visible: number): ScreenerColumn[] {
  return DEFAULT_COLUMNS.map((c, i) => ({ ...c, visible: i < visible }));
}

async function openPopover() {
  // The trigger button is labelled "Configure columns" in the SUT. Radix
  // popover content portals on click; we await the role=note element below
  // rather than asserting opens-state to avoid coupling to Radix internals.
  const trigger = screen.getByRole("button", { name: /Configure columns/i });
  await userEvent.click(trigger);
}

describe("ColumnSettingsPopover — 14-column warning footer", () => {
  it("shows the muted warning copy at the threshold (14 columns)", async () => {
    // WHY: at exactly 14 visible columns the popover stays muted (per
    // T-IA-08: "if selectedCols.length > 14, the footer is text-warning").
    // The copy stays the same so the user always sees the rule.
    render(
      <ColumnSettingsPopover
        columns={colsWithVisibleCount(14)}
        onChange={() => {}}
      />,
    );
    await openPopover();
    // WHY findByRole: Radix portals the popover content async; findBy
    // retries until the element appears (jsdom doesn't simulate paint
    // immediately).
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(
      /More than 14 columns will horizontally scroll past the 1440 px viewport/i,
    );
    // text-warning escalation must NOT be present yet at the boundary.
    expect(note.className).not.toMatch(/text-warning/);
    expect(note.className).toMatch(/text-muted-foreground/);
  });

  it("escalates the footer to text-warning above the threshold (15 columns)", async () => {
    // WHY 15 (not 100): the predicate is `> 14`. Picking 15 keeps the
    // test against the documented threshold and avoids over-asserting.
    render(
      <ColumnSettingsPopover
        columns={colsWithVisibleCount(15)}
        onChange={() => {}}
      />,
    );
    await openPopover();
    // WHY findByRole: Radix portals the popover content async; findBy
    // retries until the element appears (jsdom doesn't simulate paint
    // immediately).
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/More than 14 columns/i);
    // The escalated state swaps to the warning colour token.
    expect(note.className).toMatch(/text-warning/);
  });
});
