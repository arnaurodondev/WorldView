/**
 * components/portfolio/__tests__/PortfolioModeToggle.test.tsx — PLAN-0122 W-A
 * (T-A-A-02).
 *
 * WHY THIS EXISTS: PortfolioModeToggle is the visible Simple|Advanced switch. It
 * is presentational (mode in, onModeChange out) so it tests without a router.
 * These pin: the two segments render + reflect the active mode, a click fires the
 * callback, and the a11y/tour contract (role="radiogroup" + data-tour-target)
 * that the header and the W-F onboarding tour depend on.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PortfolioModeToggle } from "@/components/portfolio/PortfolioModeToggle";

describe("PortfolioModeToggle", () => {
  it("test_toggle_renders_two_segments: renders Simple + Advanced; active reflects mode", () => {
    render(<PortfolioModeToggle mode="advanced" onModeChange={() => {}} />);

    const simple = screen.getByRole("radio", { name: "Simple" });
    const advanced = screen.getByRole("radio", { name: "Advanced" });
    expect(simple).toBeInTheDocument();
    expect(advanced).toBeInTheDocument();

    // The active segment is the one whose value === mode ("advanced" here).
    expect(advanced).toHaveAttribute("aria-checked", "true");
    expect(simple).toHaveAttribute("aria-checked", "false");
  });

  it("test_toggle_calls_onchange: clicking Advanced fires onModeChange('advanced')", async () => {
    const onModeChange = vi.fn();
    // Start in Simple so clicking Advanced is a real change.
    render(<PortfolioModeToggle mode="simple" onModeChange={onModeChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Advanced" }));

    expect(onModeChange).toHaveBeenCalledTimes(1);
    expect(onModeChange).toHaveBeenCalledWith("advanced");
  });

  it("test_toggle_has_tour_target_and_role: radiogroup + data-tour-target present", () => {
    render(<PortfolioModeToggle mode="simple" onModeChange={() => {}} />);

    // The radiogroup is the anchor the W-F tour resolves via querySelector, and
    // the ARIA role the a11y contract requires.
    const group = screen.getByRole("radiogroup", {
      name: "Portfolio detail level",
    });
    expect(group).toHaveAttribute("data-tour-target", "mode-toggle");
  });
});
