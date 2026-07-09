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

  // ── A11Y: WAI-ARIA radiogroup keyboard pattern ─────────────────────────────

  it("test_toggle_roving_tabindex: only the checked radio is a tab stop", () => {
    // With mode=simple, Simple is checked (tabIndex 0) and Advanced is not (-1).
    render(<PortfolioModeToggle mode="simple" onModeChange={() => {}} />);

    const simple = screen.getByRole("radio", { name: "Simple" });
    const advanced = screen.getByRole("radio", { name: "Advanced" });

    // Roving tabindex: the group is a single tab stop on the checked radio.
    expect(simple).toHaveAttribute("tabindex", "0");
    expect(advanced).toHaveAttribute("tabindex", "-1");
  });

  it("test_toggle_roving_tabindex_reflects_mode: checked side flips with mode", () => {
    render(<PortfolioModeToggle mode="advanced" onModeChange={() => {}} />);

    expect(screen.getByRole("radio", { name: "Advanced" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Simple" })).toHaveAttribute("tabindex", "-1");
  });

  it("test_toggle_arrow_right_selects_next_and_fires_onchange", async () => {
    const onModeChange = vi.fn();
    render(<PortfolioModeToggle mode="simple" onModeChange={onModeChange} />);

    const simple = screen.getByRole("radio", { name: "Simple" });
    // Focus the checked radio (the roving tab stop), then press ArrowRight.
    simple.focus();
    await userEvent.keyboard("{ArrowRight}");

    // Arrow immediately selects the next segment (radiogroup pattern).
    expect(onModeChange).toHaveBeenCalledTimes(1);
    expect(onModeChange).toHaveBeenCalledWith("advanced");
    // Focus follows selection → the newly selected radio is focused.
    expect(screen.getByRole("radio", { name: "Advanced" })).toHaveFocus();
  });

  it("test_toggle_arrow_down_selects_next: ArrowDown behaves like ArrowRight", async () => {
    const onModeChange = vi.fn();
    render(<PortfolioModeToggle mode="simple" onModeChange={onModeChange} />);

    screen.getByRole("radio", { name: "Simple" }).focus();
    await userEvent.keyboard("{ArrowDown}");

    expect(onModeChange).toHaveBeenCalledWith("advanced");
  });

  it("test_toggle_arrow_left_selects_previous_and_fires_onchange", async () => {
    const onModeChange = vi.fn();
    // Start on Advanced so ArrowLeft moves back to Simple.
    render(<PortfolioModeToggle mode="advanced" onModeChange={onModeChange} />);

    screen.getByRole("radio", { name: "Advanced" }).focus();
    await userEvent.keyboard("{ArrowLeft}");

    expect(onModeChange).toHaveBeenCalledTimes(1);
    expect(onModeChange).toHaveBeenCalledWith("simple");
    expect(screen.getByRole("radio", { name: "Simple" })).toHaveFocus();
  });

  it("test_toggle_arrow_wraps: ArrowRight on the last segment wraps to the first", async () => {
    const onModeChange = vi.fn();
    render(<PortfolioModeToggle mode="advanced" onModeChange={onModeChange} />);

    screen.getByRole("radio", { name: "Advanced" }).focus();
    await userEvent.keyboard("{ArrowRight}");

    // Wraps from Advanced (last) back to Simple (first).
    expect(onModeChange).toHaveBeenCalledWith("simple");
    expect(screen.getByRole("radio", { name: "Simple" })).toHaveFocus();
  });

  it("test_toggle_home_end_select_first_and_last", async () => {
    const onModeChange = vi.fn();
    render(<PortfolioModeToggle mode="simple" onModeChange={onModeChange} />);

    const simple = screen.getByRole("radio", { name: "Simple" });
    simple.focus();

    // End → last segment (Advanced).
    await userEvent.keyboard("{End}");
    expect(onModeChange).toHaveBeenCalledWith("advanced");
    expect(screen.getByRole("radio", { name: "Advanced" })).toHaveFocus();
  });
});
