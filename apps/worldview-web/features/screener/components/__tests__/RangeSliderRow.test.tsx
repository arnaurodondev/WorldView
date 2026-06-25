/**
 * features/screener/components/__tests__/RangeSliderRow.test.tsx
 * (Round 2 — dual-thumb range sliders)
 *
 * WHAT WE TEST (and what we deliberately don't):
 *   - Render contract: two thumbs (role="slider"), the preserved RangeInput
 *     pair, the readout text, and the showInputs=false variant.
 *   - Keyboard interaction: Radix thumbs respond to arrow keys in jsdom (no
 *     layout required), so we verify a thumb nudge propagates through
 *     sliderPositionsToRange into onMin/onMax.
 *   - Mouse DRAG is NOT tested here — jsdom has no real layout so pointer
 *     coordinates are meaningless; the position→value math is covered as pure
 *     functions in lib/__tests__/slider-scale.test.ts, and drag itself is
 *     Radix's contract, not ours.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RangeSliderRow } from "../RangeSliderRow";
import { createLinearScale } from "../../lib/slider-scale";

const SCALE = createLinearScale(0, 100, 100);

function renderRow(props: Partial<React.ComponentProps<typeof RangeSliderRow>> = {}) {
  const onMin = vi.fn();
  const onMax = vi.fn();
  render(
    <RangeSliderRow
      label="P/E (TTM)"
      scale={SCALE}
      min={undefined}
      max={undefined}
      onMin={onMin}
      onMax={onMax}
      {...props}
    />,
  );
  return { onMin, onMax };
}

describe("RangeSliderRow", () => {
  it("renders two slider thumbs with lower/upper-bound aria-labels", () => {
    // WHY "lower/upper bound" naming: the words "minimum"/"maximum" belong to
    // the numeric inputs — see the WHY comment on the Thumb elements.
    renderRow();
    const thumbs = screen.getAllByRole("slider");
    expect(thumbs).toHaveLength(2);
    expect(screen.getByLabelText(/P\/E \(TTM\) lower bound slider thumb/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/P\/E \(TTM\) upper bound slider thumb/i)).toBeInTheDocument();
  });

  it("preserves the RangeInput numeric pair when showInputs is default (true)", () => {
    // CRITICAL compatibility contract: the ~70 pre-existing filter tests
    // target "<label> minimum"/"<label> maximum" inputs — the slider must be
    // additive, not a replacement.
    renderRow();
    expect(screen.getByLabelText("P/E (TTM) minimum")).toBeInTheDocument();
    expect(screen.getByLabelText("P/E (TTM) maximum")).toBeInTheDocument();
  });

  it("hides the numeric inputs when showInputs=false (Market Cap mode)", () => {
    renderRow({ showInputs: false });
    expect(screen.queryByLabelText("P/E (TTM) minimum")).not.toBeInTheDocument();
    // The label still renders inline next to the slider.
    expect(screen.getByText("P/E (TTM)")).toBeInTheDocument();
  });

  it('shows "Any" in the readout when both sides are unset', () => {
    renderRow();
    expect(screen.getByLabelText(/P\/E \(TTM\) selected range/i)).toHaveTextContent("Any");
  });

  it("shows the formatted bounds in the readout when set", () => {
    renderRow({ min: 10, max: 50, formatValue: (v) => `${v}x` });
    expect(screen.getByLabelText(/selected range/i)).toHaveTextContent("10x – 50x");
  });

  it("parks unset thumbs at the track ends (aria-valuenow = 0 / steps)", () => {
    renderRow({ min: undefined, max: undefined });
    const [lowThumb, highThumb] = screen.getAllByRole("slider");
    expect(lowThumb).toHaveAttribute("aria-valuenow", "0");
    expect(highThumb).toHaveAttribute("aria-valuenow", "100");
  });

  it("keyboard-nudging the min thumb calls onMin with the domain value", () => {
    // ArrowRight on the low thumb: position 0 → 1 → fromSlider(1) = 1 on the
    // 0..100 linear scale. This exercises the full handleSliderChange path.
    // WHY focus() first: Radix routes keyboard input to the thumb that holds
    // focus (valueIndexToChangeRef is set in the Thumb's onFocus handler) —
    // without it, keydown always targets thumb index 0.
    const { onMin, onMax } = renderRow();
    const [lowThumb] = screen.getAllByRole("slider");
    fireEvent.focus(lowThumb);
    fireEvent.keyDown(lowThumb, { key: "ArrowRight" });
    expect(onMin).toHaveBeenCalledWith(1);
    // The untouched max side must NOT be clobbered (it stayed at the end).
    expect(onMax).not.toHaveBeenCalled();
  });

  it("keyboard-nudging the max thumb back to the end clears the max (undefined)", () => {
    // max=99 → high thumb at position 99; ArrowRight moves it to 100 (the
    // track end), which by the ends-mean-unbounded rule clears the filter.
    const { onMin, onMax } = renderRow({ min: undefined, max: 99 });
    const [, highThumb] = screen.getAllByRole("slider");
    // Focus selects WHICH thumb the keyboard controls — see comment above.
    fireEvent.focus(highThumb);
    fireEvent.keyDown(highThumb, { key: "ArrowRight" });
    expect(onMax).toHaveBeenCalledWith(undefined);
    expect(onMin).not.toHaveBeenCalled();
  });
});

// ── Round-4 item 2: slider thumb aria-valuetext ───────────────────────────────
//
// WHY: Radix announces the raw integer TRACK POSITION via aria-valuenow
// (0…steps) — meaningless to screen-reader users ("142" instead of "$7.1B").
// Round 4 adds aria-valuetext with the human-readable domain value, using the
// SAME formatter as the visual readout so eyes and ears agree.

describe("RangeSliderRow — aria-valuetext (Round 4 a11y)", () => {
  it("announces human-readable formatted values on set thumbs", () => {
    renderRow({ min: 10, max: 50, formatValue: (v) => `$${v}M` });
    const [lowThumb, highThumb] = screen.getAllByRole("slider");
    // The formatted DOMAIN value, not the raw slider position integer.
    expect(lowThumb).toHaveAttribute("aria-valuetext", "$10M");
    expect(highThumb).toHaveAttribute("aria-valuetext", "$50M");
  });

  it('announces "Any (no … bound)" on unset thumbs instead of a phantom end value', () => {
    // Unset thumbs park at the track ends; without valuetext AT would read
    // "0" / "100" — implying a constraint that does not exist.
    renderRow({ min: undefined, max: undefined });
    const [lowThumb, highThumb] = screen.getAllByRole("slider");
    expect(lowThumb).toHaveAttribute("aria-valuetext", "Any (no lower bound)");
    expect(highThumb).toHaveAttribute("aria-valuetext", "Any (no upper bound)");
  });

  it("aria-valuetext tracks one-sided ranges independently", () => {
    renderRow({ min: 25, max: undefined, formatValue: (v) => `${v}%` });
    const [lowThumb, highThumb] = screen.getAllByRole("slider");
    expect(lowThumb).toHaveAttribute("aria-valuetext", "25%");
    expect(highThumb).toHaveAttribute("aria-valuetext", "Any (no upper bound)");
  });
});
