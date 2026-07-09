/**
 * components/portfolio/__tests__/HoldingsColumnGroupToggle.test.tsx —
 * PLAN-0122 W-E (T-A-E-03).
 *
 * Verifies the ⚙ popover: Core locked-on, Portfolio/Advanced toggle + persist,
 * Reset restores the Advanced default, the toggle is hidden in Simple mode, and
 * the data-tour-target anchor (consumed by W-F) is present.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { HoldingsColumnGroupToggle } from "../HoldingsColumnGroupToggle";
import {
  HOLDINGS_COL_GROUPS_KEY,
  ADVANCED_GROUP_DEFAULT,
  type HoldingsColGroups,
} from "@/lib/portfolio/holdings-column-groups";

function open() {
  fireEvent.click(screen.getByRole("button", { name: /show or hide table columns/i }));
}

describe("PLAN-0122 W-E · HoldingsColumnGroupToggle (R-27)", () => {
  beforeEach(() => window.localStorage.clear());

  it("test_column_toggle_has_tour_target: gear carries data-tour-target", () => {
    render(
      <HoldingsColumnGroupToggle groups={ADVANCED_GROUP_DEFAULT} onChange={() => {}} />,
    );
    const gear = screen.getByRole("button", { name: /show or hide table columns/i });
    expect(gear.getAttribute("data-tour-target")).toBe("column-toggle");
  });

  it("test_column_toggle_hidden_in_simple: nothing renders in Simple mode", () => {
    const { container } = render(
      <HoldingsColumnGroupToggle
        mode="simple"
        groups={ADVANCED_GROUP_DEFAULT}
        onChange={() => {}}
      />,
    );
    // Whole control is gated out — no gear button at all.
    expect(container).toBeEmptyDOMElement();
    expect(
      screen.queryByRole("button", { name: /show or hide table columns/i }),
    ).not.toBeInTheDocument();
  });

  it("test_column_group_toggle_persists_and_gates: Portfolio off hides + persists; Core locked", () => {
    const onChange = vi.fn();
    render(
      <HoldingsColumnGroupToggle groups={ADVANCED_GROUP_DEFAULT} onChange={onChange} />,
    );
    open();

    // Core checkbox is checked + disabled (locked anchor group).
    const core = screen.getByRole("checkbox", { name: /core columns \(always shown\)/i });
    expect(core).toBeChecked();
    expect(core).toBeDisabled();

    // Toggle Portfolio OFF.
    const portfolio = screen.getByRole("checkbox", { name: /toggle portfolio detail/i });
    expect(portfolio).toBeChecked();
    fireEvent.click(portfolio);

    // onChange fired with portfolio:false, core still on.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ core: true, portfolio: false, advanced: true }),
    );
    // Persisted to worldview:holdingsColGroups:v1.
    const saved: HoldingsColGroups = JSON.parse(
      window.localStorage.getItem(HOLDINGS_COL_GROUPS_KEY)!,
    );
    expect(saved).toEqual({ core: true, portfolio: false, advanced: true });
  });

  it("test_column_toggle_reset_restores_default: Reset → Advanced default", () => {
    const onChange = vi.fn();
    // Start from a non-default state (portfolio off, advanced off).
    render(
      <HoldingsColumnGroupToggle
        groups={{ core: true, portfolio: false, advanced: false }}
        onChange={onChange}
      />,
    );
    open();
    fireEvent.click(screen.getByRole("button", { name: /reset columns to default/i }));
    expect(onChange).toHaveBeenCalledWith(ADVANCED_GROUP_DEFAULT);
    expect(JSON.parse(window.localStorage.getItem(HOLDINGS_COL_GROUPS_KEY)!)).toEqual(
      ADVANCED_GROUP_DEFAULT,
    );
  });
});
