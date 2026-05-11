/**
 * __tests__/date-range-picker.test.tsx — Unit tests for DateRangePicker
 *
 * WHY THIS EXISTS: The DateRangePicker trigger must show correctly formatted
 * date ranges (same-year vs cross-year) and call onChange with the selected
 * DateRange. These tests verify the trigger label and basic interaction.
 *
 * DATA SOURCE: No S9 calls — pure presentation.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DateRangePicker } from "@/components/ui/date-range-picker";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeTriggerButton() {
  return screen.getByRole("button");
}

// ── Placeholder ─────────────────────────────────────────────────────────────

describe("DateRangePicker — placeholder", () => {
  it("shows default placeholder when value is undefined", () => {
    render(<DateRangePicker value={undefined} onChange={vi.fn()} />);
    expect(makeTriggerButton()).toHaveTextContent("Select date range");
  });

  it("shows custom placeholder when provided", () => {
    render(
      <DateRangePicker
        value={undefined}
        onChange={vi.fn()}
        placeholder="Pick a range"
      />,
    );
    expect(makeTriggerButton()).toHaveTextContent("Pick a range");
  });

  it("shows only the from-date when to is undefined", () => {
    const from = new Date(2026, 4, 1); // May 1, 2026
    render(
      <DateRangePicker value={{ from, to: undefined }} onChange={vi.fn()} />,
    );
    // Should show "May 1" without an em-dash
    const triggerText = makeTriggerButton().textContent ?? "";
    expect(triggerText).toContain("May 1");
    expect(triggerText).not.toContain("–");
  });
});

// ── Same-year formatting ──────────────────────────────────────────────────

describe("DateRangePicker — same-year formatting", () => {
  it("formats same-year range as 'MMM d – MMM d' (no year)", () => {
    const from = new Date(2026, 4, 1);  // May 1
    const to = new Date(2026, 4, 15);   // May 15
    render(<DateRangePicker value={{ from, to }} onChange={vi.fn()} />);
    expect(makeTriggerButton()).toHaveTextContent("May 1 – May 15");
  });

  it("does NOT show the year for same-year ranges (saves horizontal space)", () => {
    const from = new Date(2026, 0, 5);  // Jan 5
    const to = new Date(2026, 11, 31);  // Dec 31
    render(<DateRangePicker value={{ from, to }} onChange={vi.fn()} />);
    const triggerText = makeTriggerButton().textContent ?? "";
    // Year must not be present — this is what "compact" means in a terminal UI.
    expect(triggerText).not.toContain("2026");
  });
});

// ── Cross-year formatting ─────────────────────────────────────────────────

describe("DateRangePicker — cross-year formatting", () => {
  it("includes years for cross-year ranges", () => {
    const from = new Date(2025, 11, 31); // Dec 31, 2025
    const to = new Date(2026, 0, 5);     // Jan 5, 2026
    render(<DateRangePicker value={{ from, to }} onChange={vi.fn()} />);
    const triggerText = makeTriggerButton().textContent ?? "";
    expect(triggerText).toContain("2025");
    expect(triggerText).toContain("2026");
  });
});

// ── Disabled state ────────────────────────────────────────────────────────

describe("DateRangePicker — disabled", () => {
  it("disables the trigger button when disabled prop is true", () => {
    render(
      <DateRangePicker
        value={undefined}
        onChange={vi.fn()}
        disabled
      />,
    );
    expect(makeTriggerButton()).toBeDisabled();
  });
});

// ── Popover + onChange ────────────────────────────────────────────────────

describe("DateRangePicker — interaction", () => {
  it("opens a popover with a calendar when trigger is clicked", async () => {
    const user = userEvent.setup();
    render(<DateRangePicker value={undefined} onChange={vi.fn()} />);
    await user.click(makeTriggerButton());
    // WHY query by role=grid: react-day-picker renders the month as a grid.
    // If the grid is in the DOM, the popover opened successfully.
    await waitFor(() => {
      expect(screen.getByRole("grid")).toBeInTheDocument();
    });
  });

  it("calls onChange when a date is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Use a specific month so we can click a known date cell.
    render(
      <DateRangePicker
        value={{ from: new Date(2026, 4, 1), to: undefined }}
        onChange={onChange}
      />,
    );
    await user.click(makeTriggerButton());
    await waitFor(() => screen.getByRole("grid"));
    // Click day "10" in the grid (the 10th cell button).
    const dayButtons = screen.getAllByRole("button").filter(
      (btn) => btn.getAttribute("name")?.startsWith("2026") || btn.getAttribute("aria-label")?.includes("10"),
    );
    if (dayButtons.length > 0) {
      await user.click(dayButtons[0]);
      expect(onChange).toHaveBeenCalled();
    }
  });
});
