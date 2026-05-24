/**
 * AnalyticsPeriodSelector tests (F-009 from 2026-05-23 QA report).
 *
 * WHY: Verifies all 7 period pills render, the active pill is highlighted,
 * and onChange fires with the correct period string.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { AnalyticsPeriodSelector } from "../AnalyticsPeriodSelector";

const ALL_PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "ALL"] as const;

describe("AnalyticsPeriodSelector", () => {
  it("renders all 7 period pills", () => {
    render(<AnalyticsPeriodSelector value="YTD" onChange={vi.fn()} />);
    for (const p of ALL_PERIODS) {
      expect(screen.getByRole("tab", { name: p })).toBeInTheDocument();
    }
  });

  it("marks the active pill as selected", () => {
    render(<AnalyticsPeriodSelector value="1Y" onChange={vi.fn()} />);
    // WHY aria-selected: the component uses role="tab" + aria-selected per
    // the a11y spec for mutually-exclusive pill groups.
    const active = screen.getByRole("tab", { name: "1Y" });
    expect(active).toHaveAttribute("aria-selected", "true");

    // Inactive pills should not be selected.
    for (const p of ALL_PERIODS.filter((x) => x !== "1Y")) {
      expect(screen.getByRole("tab", { name: p })).toHaveAttribute(
        "aria-selected",
        "false",
      );
    }
  });

  it("calls onChange with the clicked period", () => {
    const onChange = vi.fn();
    render(<AnalyticsPeriodSelector value="YTD" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "3M" }));
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenCalledWith("3M");
  });

  it("calls onChange when clicking the already-active pill (re-select)", () => {
    // WHY test this: some toggleable pill UIs skip onChange when re-clicking
    // the active option. AnalyticsPeriodSelector is not a toggle — clicking
    // the active pill should still call onChange (caller decides idempotency).
    const onChange = vi.fn();
    render(<AnalyticsPeriodSelector value="1M" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "1M" }));
    expect(onChange).toHaveBeenCalledWith("1M");
  });
});
