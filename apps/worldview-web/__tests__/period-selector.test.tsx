/**
 * __tests__/period-selector.test.tsx — Unit tests for PeriodSelector
 *
 * WHY THIS EXISTS: PeriodSelector is shared by multiple widgets; this pins
 * the click → onSelect contract and the active-state styling so refactors
 * cannot silently break period switching across the dashboard.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PeriodSelector } from "@/components/ui/period-selector";

describe("PeriodSelector", () => {
  it("renders a button per period", () => {
    render(
      <PeriodSelector
        periods={["1D", "1W", "1M"]}
        selected="1D"
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "1D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1W" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1M" })).toBeInTheDocument();
  });

  it("marks the selected period with aria-pressed=true", () => {
    render(
      <PeriodSelector
        periods={["1D", "1W", "1M"]}
        selected="1W"
        onSelect={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: "1W" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByRole("button", { name: "1D" }).getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("calls onSelect with the clicked period", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <PeriodSelector
        periods={["1D", "1W", "1M"]}
        selected="1D"
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole("button", { name: "1M" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("1M");
  });

  it("uses the supplied ariaLabel for the group", () => {
    render(
      <PeriodSelector
        periods={["1D"]}
        selected="1D"
        onSelect={() => {}}
        ariaLabel="Heatmap period"
      />,
    );
    expect(
      screen.getByRole("group", { name: "Heatmap period" }),
    ).toBeInTheDocument();
  });

  it("falls back to default ariaLabel='Period'", () => {
    render(
      <PeriodSelector periods={["1D"]} selected="1D" onSelect={() => {}} />,
    );
    expect(screen.getByRole("group", { name: "Period" })).toBeInTheDocument();
  });

  it("active button uses primary tint, inactive uses muted", () => {
    render(
      <PeriodSelector
        periods={["1D", "1W"]}
        selected="1D"
        onSelect={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "1D" }).className).toContain(
      "bg-primary/20",
    );
    expect(screen.getByRole("button", { name: "1W" }).className).toContain(
      "text-muted-foreground",
    );
  });
});
