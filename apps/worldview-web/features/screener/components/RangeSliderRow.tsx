"use client";

/**
 * features/screener/components/RangeSliderRow.tsx — Dual-thumb range slider
 * (optionally) paired with the existing min/max numeric inputs.
 * (Round 2 enhancement — product spec: range sliders for Market Cap, P/E,
 * Div Yield, ROE, and 30d Avg Volume.)
 *
 * WHY A NEW COMPONENT (instead of editing RangeInput):
 *   - RangeInput's exact markup/aria-labels are pinned by ~70 existing filter
 *     tests ("<label> minimum"/"<label> maximum"). Wrapping it — rather than
 *     rewriting it — keeps every one of those assertions valid.
 *   - The slider is purely ADDITIVE UX: the numeric inputs remain the precise
 *     entry path (and the only path for values outside the slider domain);
 *     the slider is the fast coarse-adjust path. Both write the SAME
 *     FilterState keys, so build-filters.ts and the chip strip need zero
 *     changes to understand slider-set values.
 *
 * WHY RADIX PRIMITIVES DIRECTLY (not components/ui/slider.tsx):
 *   - The shadcn wrapper in components/ui/slider.tsx renders exactly ONE
 *     <Thumb> — it's a single-value slider. A range filter needs two thumbs,
 *     which Radix supports natively via value={[low, high]} + two <Thumb>
 *     children. components/ui/ is outside this surface's ownership (five
 *     agents run concurrently), so we compose the same Radix primitive here
 *     with byte-identical track/range/thumb styling. If the ui/ wrapper ever
 *     grows multi-thumb support, this can collapse onto it.
 *
 * SLIDER ↔ FILTER MAPPING (see slider-scale.ts for the math):
 *   - Thumb at a track END = that side UNCONSTRAINED (undefined in
 *     FilterState), so an untouched slider adds no filter and dragging a
 *     thumb back to the end clears that side.
 *   - Values produced by the slider are rounded to 3 significant digits so
 *     chips read "$10B" instead of "$10.234567891B".
 *
 * WHY onValueChange (live) and not onValueCommit:
 *   - The ScreenerFilterBar keeps a LOCAL form state that only hits the
 *     network on the explicit Apply button. Live updates are therefore free
 *     (pure React state) and let the readout + numeric inputs track the
 *     thumbs in real time. If this slider is ever reused in a live-query
 *     context, switch to onValueCommit.
 */

import * as SliderPrimitive from "@radix-ui/react-slider";
import { cn } from "@/lib/utils";
import { RangeInput, type RangeInputProps } from "./RangeInput";
import {
  type SliderScale,
  rangeToSliderPositions,
  sliderPositionsToRange,
} from "../lib/slider-scale";

// ── Props ────────────────────────────────────────────────────────────────────

export interface RangeSliderRowProps extends Omit<RangeInputProps, "disabled" | "disabledReason"> {
  /** Domain↔slider mapping (linear or log) — see slider-scale.ts. */
  scale: SliderScale;
  /**
   * Render the min/max numeric inputs above the slider (default true).
   * Market Cap sets false: typing raw USD (10000000000) is worse UX than the
   * log slider + formatted readout, and the chip strip already offers exact
   * "$NB" entry for power users.
   */
  showInputs?: boolean;
  /**
   * Formats a domain value for the slider readout (e.g. $1.5B, 2.5%, 1.2M).
   * Defaults to String(v). Keep it compact — the readout sits inline.
   */
  formatValue?: (v: number) => string;
}

// ── Component ────────────────────────────────────────────────────────────────

export function RangeSliderRow({
  scale,
  showInputs = true,
  formatValue = (v) => String(v),
  ...rangeInputProps
}: RangeSliderRowProps) {
  const { label, min, max, onMin, onMax } = rangeInputProps;

  // Derive thumb positions FROM the canonical filter values (single source of
  // truth = FilterState). No local slider state — typing into the numeric
  // inputs moves the thumbs, and dragging the thumbs updates the inputs,
  // because both read/write the same min/max props.
  const positions = rangeToSliderPositions(min, max, scale);

  /**
   * handleSliderChange — Radix emits [low, high] integer positions; convert
   * back to domain values with the ends-mean-unbounded rule and propagate
   * only the side(s) that actually changed (avoids clobbering a precise
   * typed value on the untouched side with its rounded slider equivalent).
   */
  function handleSliderChange(next: number[]): void {
    const [lowPos, highPos] = next as [number, number];
    const range = sliderPositionsToRange([lowPos, highPos], scale);
    if (lowPos !== positions[0]) onMin(range.min);
    if (highPos !== positions[1]) onMax(range.max);
  }

  // Readout text: "Any – $10B", "$1B – $50B", or "Any" when fully open.
  // WHY a readout at all: with showInputs=false (Market Cap) the slider is
  // the only control — the user needs to see the currently selected bounds.
  const readout =
    min === undefined && max === undefined
      ? "Any"
      : `${min === undefined ? "Any" : formatValue(min)} – ${max === undefined ? "Any" : formatValue(max)}`;

  return (
    <div className="flex flex-col gap-1">
      {/* Numeric inputs row — the precise-entry path; unchanged RangeInput so
          existing aria-label-based tests keep passing. */}
      {showInputs && <RangeInput {...rangeInputProps} />}

      {/* Slider row — indented to align with the inputs (label column is w-24
          + gap-2 in RangeInput, so ml = 6.5rem keeps the track under the
          input pair). When inputs are hidden the label renders inline. */}
      <div className={cn("flex items-center gap-2", showInputs && "pl-[6.5rem]")}>
        {!showInputs && (
          <span className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-24 shrink-0">
            {label}
          </span>
        )}

        <SliderPrimitive.Root
          // Controlled: positions derive from FilterState (see above).
          value={[positions[0], positions[1]]}
          onValueChange={handleSliderChange}
          min={0}
          max={scale.steps}
          step={1}
          // WHY minStepsBetweenThumbs=0: crossing is already prevented by
          // Radix; allowing thumbs to meet expresses "exactly X" ranges.
          aria-label={`${label} range slider`}
          // Track/range/thumb classes mirror components/ui/slider.tsx so the
          // two slider flavours are visually indistinguishable (see file-level
          // WHY for why we can't import that wrapper).
          className="relative flex w-44 touch-none select-none items-center"
        >
          <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-input">
            <SliderPrimitive.Range className="absolute h-full bg-primary" />
          </SliderPrimitive.Track>
          {/* Two thumbs = dual-range. Each gets its own aria-label so screen
              readers (and tests) can target the low vs high thumb.
              WHY "lower/upper bound" (NOT "minimum"/"maximum"): the numeric
              inputs already own the accessible names "<label> minimum" /
              "<label> maximum", and several pre-existing page tests query
              them with loose regexes (/p\/e .*ttm.*minimum/i). Reusing the
              word would make those queries ambiguous (two matches) — distinct
              wording keeps both controls uniquely addressable. */}
          <SliderPrimitive.Thumb
            aria-label={`${label} lower bound slider thumb`}
            className="block h-3.5 w-3.5 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:bg-[hsl(var(--disabled-bg))] disabled:border-[hsl(var(--disabled-border))]"
          />
          <SliderPrimitive.Thumb
            aria-label={`${label} upper bound slider thumb`}
            className="block h-3.5 w-3.5 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:bg-[hsl(var(--disabled-bg))] disabled:border-[hsl(var(--disabled-border))]"
          />
        </SliderPrimitive.Root>

        {/* Live readout — font-mono tabular numerics per ADR-F-15. */}
        <span
          className="font-mono text-[10px] tabular-nums text-muted-foreground whitespace-nowrap"
          aria-label={`${label} selected range`}
        >
          {readout}
        </span>
      </div>
    </div>
  );
}
