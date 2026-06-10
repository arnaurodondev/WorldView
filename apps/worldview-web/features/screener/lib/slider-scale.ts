/**
 * features/screener/lib/slider-scale.ts — Pure slider↔domain mapping math
 * (Round 2 enhancement — dual-thumb range sliders for screener filters)
 *
 * WHY THIS EXISTS: the screener's range sliders (Market Cap, P/E, Div Yield,
 * ROE, Avg Volume) need to translate between two coordinate systems:
 *
 *   SLIDER SPACE — integer thumb positions 0..steps (what Radix Slider emits)
 *   DOMAIN SPACE — real metric values (USD market cap, P/E ratio, decimal %)
 *
 * The translation is NOT always linear. Market cap spans $10M → $5T — nine
 * orders of magnitude. On a linear slider the entire small/mid-cap universe
 * ($10M–$10B) would occupy the first ~0.2% of the track: physically
 * un-grabbable. A LOG scale gives every order of magnitude equal track width,
 * so "$100M–$1B" is as easy to select as "$100B–$1T". Same reasoning applies
 * to 30-day average volume (10K → 1B shares).
 *
 * WHY A SEPARATE PURE MODULE (not inline in the component):
 *   - The math is the risky part — it gets dedicated unit tests with no DOM.
 *   - Radix sliders are awkward to "drag" in jsdom; testing the mapping as
 *     pure functions covers the correctness without browser automation.
 *
 * WHO USES IT:
 *   - features/screener/components/RangeSliderRow.tsx (the UI component)
 *   - features/screener/lib/__tests__/slider-scale.test.ts (the tests)
 */

// ── Scale abstraction ────────────────────────────────────────────────────────

/**
 * SliderScale — a bidirectional mapping between slider positions and domain
 * values.
 *
 * INVARIANTS (pinned by tests):
 *   - toSlider(domainMin) === 0 and toSlider(domainMax) === steps
 *   - fromSlider(toSlider(v)) ≈ v (round-trip within rounding tolerance)
 *   - both functions are monotonically increasing
 */
export interface SliderScale {
  /** Lower bound of the metric domain (slider position 0). */
  domainMin: number;
  /** Upper bound of the metric domain (slider position `steps`). */
  domainMax: number;
  /** Number of discrete slider steps (Radix `max` with `min=0, step=1`). */
  steps: number;
  /** Domain value → slider position (0..steps, clamped + rounded). */
  toSlider(value: number): number;
  /** Slider position (0..steps) → domain value. */
  fromSlider(position: number): number;
}

/** Clamp helper — keeps positions/values inside the configured bounds. */
function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/**
 * createLinearScale — plain proportional mapping.
 *
 * Used for metrics whose useful range spans ≲2 orders of magnitude
 * (P/E 0–100, dividend yield 0–0.10, ROE −0.5–1.0). Linear is the right
 * choice there because users think in absolute increments ("P/E of 15 vs
 * 20"), not multiplicative ones.
 */
export function createLinearScale(
  domainMin: number,
  domainMax: number,
  steps = 200,
): SliderScale {
  if (!(domainMax > domainMin)) {
    throw new Error(`createLinearScale: domainMax (${domainMax}) must exceed domainMin (${domainMin})`);
  }
  const span = domainMax - domainMin;
  return {
    domainMin,
    domainMax,
    steps,
    toSlider(value: number): number {
      // Normalise to 0..1, scale to 0..steps, round to the integer grid that
      // Radix emits (step=1). Clamp so out-of-domain typed values (the numeric
      // inputs accept anything) park the thumb at the nearest end.
      const t = (clamp(value, domainMin, domainMax) - domainMin) / span;
      return Math.round(t * steps);
    },
    fromSlider(position: number): number {
      const t = clamp(position, 0, steps) / steps;
      return domainMin + t * span;
    },
  };
}

/**
 * createLogScale — logarithmic mapping for metrics spanning many decades.
 *
 * THE MATH (this is the part the task brief asks to be commented):
 *
 *   We want equal slider distance per multiplicative factor, i.e. the slider
 *   position should be linear in log(value). Define:
 *
 *     lo = ln(domainMin),  hi = ln(domainMax)
 *
 *   Forward (domain → slider):
 *     t = (ln(value) − lo) / (hi − lo)        // 0..1, linear in log space
 *     position = round(t × steps)
 *
 *   Inverse (slider → domain):
 *     t = position / steps
 *     value = e^(lo + t × (hi − lo))
 *           = domainMin × (domainMax / domainMin)^t   // equivalent form
 *
 *   CONSEQUENCE: the slider midpoint (t = 0.5) lands on the GEOMETRIC mean
 *   √(domainMin × domainMax), not the arithmetic mean. For market cap
 *   $10M → $5T the midpoint is ≈ $7.1B — exactly the small/large-cap divide
 *   a user expects in the middle of the track. A linear slider's midpoint
 *   would be $2.5T, leaving 99.9% of listed companies in the first half-pixel.
 *
 * PRECONDITION: domainMin > 0 (ln is undefined at 0). Metrics that can be
 * zero/negative (returns, margins) must use the linear scale instead.
 */
export function createLogScale(
  domainMin: number,
  domainMax: number,
  steps = 200,
): SliderScale {
  if (domainMin <= 0) {
    throw new Error(`createLogScale: domainMin must be > 0 (got ${domainMin}) — ln(x≤0) is undefined`);
  }
  if (!(domainMax > domainMin)) {
    throw new Error(`createLogScale: domainMax (${domainMax}) must exceed domainMin (${domainMin})`);
  }
  const lo = Math.log(domainMin);
  const hi = Math.log(domainMax);
  const logSpan = hi - lo;
  return {
    domainMin,
    domainMax,
    steps,
    toSlider(value: number): number {
      // Clamp BEFORE taking the log — a typed value of 0 (or negative) from
      // the free-form numeric inputs would otherwise produce -Infinity/NaN.
      const v = clamp(value, domainMin, domainMax);
      const t = (Math.log(v) - lo) / logSpan;
      return Math.round(t * steps);
    },
    fromSlider(position: number): number {
      const t = clamp(position, 0, steps) / steps;
      return Math.exp(lo + t * logSpan);
    },
  };
}

// ── Range ↔ thumb-position mapping (the "ends mean unbounded" rule) ─────────

/**
 * rangeToSliderPositions — converts an optional {min,max} filter range to the
 * [low, high] thumb positions.
 *
 * RULE: an UNSET side (undefined) parks its thumb at the track end. This is
 * the inverse of sliderPositionsToRange below, so a user who never touches
 * the slider keeps an unconstrained filter.
 */
export function rangeToSliderPositions(
  min: number | undefined,
  max: number | undefined,
  scale: SliderScale,
): [number, number] {
  const lowPos = min === undefined ? 0 : scale.toSlider(min);
  const highPos = max === undefined ? scale.steps : scale.toSlider(max);
  // Guard inverted ranges (user typed min > max into the numeric inputs):
  // Radix requires value[0] ≤ value[1] or thumbs overlap erratically.
  return lowPos <= highPos ? [lowPos, highPos] : [highPos, lowPos];
}

/**
 * sliderPositionsToRange — converts thumb positions back to the optional
 * {min,max} filter range.
 *
 * RULE (the critical UX decision): a thumb resting at the track END means
 * "no constraint on this side" → undefined, NOT domainMin/domainMax.
 *
 * WHY: if we wrote domainMin/domainMax into FilterState, every slider touch
 * would add a hard server-side bound (e.g. market_cap ≤ $5T) that silently
 * excludes instruments with missing data — the backend INNER JOINs on each
 * filtered metric (see BP-368 in build-filters.test.ts). Mapping the ends to
 * undefined keeps "slider at rest" === "filter off", and means dragging a
 * thumb back to the end fully clears that side of the filter.
 */
export function sliderPositionsToRange(
  positions: readonly [number, number],
  scale: SliderScale,
  /**
   * Significant digits to round produced values to. Log-scale inversion
   * produces values like 10234567890.123 — rounding to 2–3 significant
   * digits gives clean chips ("$10B", not "$10.23456789B").
   */
  significantDigits = 3,
): { min: number | undefined; max: number | undefined } {
  const [lowPos, highPos] = positions;
  return {
    min: lowPos <= 0 ? undefined : roundToSignificant(scale.fromSlider(lowPos), significantDigits),
    max: highPos >= scale.steps ? undefined : roundToSignificant(scale.fromSlider(highPos), significantDigits),
  };
}

/**
 * roundToSignificant — round to N significant digits (not decimal places).
 *
 * WHY significant digits (not toFixed): the slider domain spans magnitudes —
 * 2 decimal places is absurd for $1,234,567,890 and useless for 0.0123.
 * Significant-digit rounding adapts: 1.23e9 stays $1.23B, 0.0123 stays 1.23%.
 */
export function roundToSignificant(value: number, digits = 3): number {
  if (value === 0 || !Number.isFinite(value)) return value;
  const magnitude = Math.floor(Math.log10(Math.abs(value)));
  const factor = 10 ** (digits - 1 - magnitude);
  return Math.round(value * factor) / factor;
}

// ── Compact display formatting (slider readouts + chips) ────────────────────

/**
 * formatCompactNumber — 1234567 → "1.23M", 2.5e12 → "2.5T".
 *
 * WHY local (not Intl.NumberFormat compact): Intl's "compact" notation is
 * locale-dependent ("1,2 Mio." in de-DE) — the terminal convention is the
 * fixed US-style K/M/B/T suffix set regardless of browser locale, matching
 * the AG Grid column formatters.
 */
export function formatCompactNumber(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const fmt = (v: number, suffix: string): string => {
    // Trim trailing ".0" so we render "5B" not "5.0B" — but keep one decimal
    // of precision for non-round values ("1.5B").
    const s = v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1).replace(/\.0$/, "") : v.toFixed(2).replace(/\.?0+$/, "");
    return `${sign}${s}${suffix}`;
  };
  if (abs >= 1e12) return fmt(abs / 1e12, "T");
  if (abs >= 1e9) return fmt(abs / 1e9, "B");
  if (abs >= 1e6) return fmt(abs / 1e6, "M");
  if (abs >= 1e3) return fmt(abs / 1e3, "K");
  return `${sign}${abs % 1 === 0 ? abs.toFixed(0) : abs.toFixed(2)}`;
}
