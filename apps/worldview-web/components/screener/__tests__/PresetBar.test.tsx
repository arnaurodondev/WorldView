/**
 * components/screener/__tests__/PresetBar.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: PresetBar is the row-1 quick-screen affordance shipped in T-IA-01.
 * The visual contract (active vs inactive pill) and click handler are the
 * two behaviours every consumer depends on; pin them here so future style
 * tweaks must update an explicit test instead of slipping past review.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PresetBar } from "@/components/screener/PresetBar";
import type { ScreenerPreset } from "@/lib/screener/presets";

// WHY a fixture (not the real SCREENER_PRESETS): tests should not break
// when the curated preset list grows / shrinks. The fixture is the
// minimum shape needed to exercise active highlighting + click handling.
const FIXTURE: readonly ScreenerPreset[] = [
  {
    id: "all",
    label: "All",
    // Cast: ScreenerPreset.filters is FilterState — but the bar never
    // reads inside that object, only forwards it to onApply. An `as`
    // cast lets us avoid materialising the entire DEFAULT_FILTERS shape
    // in this test fixture.
    filters: {} as ScreenerPreset["filters"],
  },
  {
    id: "large-cap",
    label: "Large Cap",
    filters: {} as ScreenerPreset["filters"],
  },
];

describe("PresetBar", () => {
  it("renders one chip per preset", () => {
    render(<PresetBar presets={FIXTURE} activeId={null} onApply={() => {}} />);
    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Large Cap" })).toBeInTheDocument();
  });

  it("marks the active chip with aria-pressed=true", () => {
    // WHY aria-pressed (not class): the active styling drives the visual
    // contract but assistive tech only sees the ARIA attribute. We assert
    // the a11y contract; the class string is incidental.
    render(
      <PresetBar presets={FIXTURE} activeId="large-cap" onApply={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "Large Cap" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("calls onApply with the clicked preset", async () => {
    const onApply = vi.fn();
    render(
      <PresetBar presets={FIXTURE} activeId={null} onApply={onApply} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Large Cap" }));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith(FIXTURE[1]);
  });

  it("renders the '+ New preset' button only when onSavePreset is supplied", () => {
    // WHY two render passes: the trailing save button is opt-in (the plan
    // states "only when onSavePreset is defined"). The absence pass guards
    // against an accidental always-render that would promise un-shipped UX.
    const { rerender } = render(
      <PresetBar presets={FIXTURE} activeId={null} onApply={() => {}} />,
    );
    expect(screen.queryByText(/\+ New preset/i)).not.toBeInTheDocument();
    rerender(
      <PresetBar
        presets={FIXTURE}
        activeId={null}
        onApply={() => {}}
        onSavePreset={() => {}}
      />,
    );
    expect(screen.getByText(/\+ New preset/i)).toBeInTheDocument();
  });
});
