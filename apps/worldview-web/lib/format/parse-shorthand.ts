/**
 * lib/format/parse-shorthand.ts — TradingView-style numeric shorthand parser
 *
 * WHY THIS EXISTS: Institutional traders type values fast. Bloomberg, TradingView,
 * and FactSet all accept compact shorthand inputs:
 *   - "1.5m" → 1500000              (mega = millions)
 *   - "2.3b" → 2300000000           (billions)
 *   - "850k" → 850000               (kilos)
 *   - "1.2t" → 1200000000000        (trillions)
 *   - "+2%" → 0.02                  (percent — fractional)
 *   - "-15%" → -0.15
 *   - "25bps" → 0.0025              (basis points)
 *   - "1,234.56" → 1234.56          (locale digits)
 *   - "(500)" → -500                (accounting negative)
 *   - "$1.5m" → 1500000             (currency-stripped)
 *   - "" / null / "abc" → null      (invalid)
 *
 * WHY a single canonical parser: every form-input that accepts a number has been
 * inventing its own "remove $ then parseFloat" hack. This causes inconsistencies
 * (one form accepts "1.5m", another rejects it, a third treats "M" differently
 * from "m"). Centralising the rules guarantees one user mental model across
 * the whole app.
 *
 * WHY return null on invalid (vs NaN or 0): `null` forces callers to handle the
 * "no value" case explicitly. `NaN` silently propagates through arithmetic; `0`
 * is a valid input that means something different.
 *
 * SECURITY: regex has bounded matches; no catastrophic backtracking risk. All
 * inputs are coerced to string and trimmed before any pattern application.
 *
 * USED BY: components/ui/number-input.tsx, screener filter price/cap inputs,
 * trade-ticket quantity input, alert-rule threshold input.
 */

export interface ShorthandOptions {
  /**
   * If true, "%" suffix returns the *fractional* representation (2% → 0.02).
   * If false, "%" returns the *literal* number (2% → 2).
   * WHY default true: most callers store decimals (e.g. `daily_return`).
   * Callers that want a percent-as-number (e.g. allocation slider) pass false.
   */
  percentAsFraction?: boolean;

  /**
   * If true, basis-points suffix ("bps") parses as fraction (25bps → 0.0025).
   * If false, returns literal number (25bps → 25).
   */
  bpsAsFraction?: boolean;
}

const DEFAULT_OPTIONS: Required<ShorthandOptions> = {
  percentAsFraction: true,
  bpsAsFraction: true,
};

// Multipliers for SI suffixes. WHY a Map: O(1) lookup; explicit; easy to extend.
const SI_MULTIPLIERS: Record<string, number> = {
  k: 1_000,
  m: 1_000_000,
  b: 1_000_000_000,
  t: 1_000_000_000_000,
};

/**
 * STRICT_NUMBER — guard against `parseFloat`'s greedy leniency. `parseFloat("1m2")`
 * returns 1 (parses prefix, ignores garbage). For shorthand, "1m2b" is ambiguous
 * garbage, not "1B". Apply this regex to the numeric portion before `parseFloat`
 * to reject any tail beyond a clean signed decimal (with optional exponent).
 *
 * Supports: "100", "1.5", "-2.3", ".5", "-0.5", "1e10", "1.5e-7", "-1E+3".
 * Scientific notation lets very small floats round-trip cleanly through
 * NumberInput (parent value 1e-7 → display "1e-7" → parse back to 1e-7).
 */
const STRICT_NUMBER = /^-?(\d+(\.\d+)?|\.\d+)([eE][+-]?\d+)?$/;

function strictParseFloat(s: string): number | null {
  if (!STRICT_NUMBER.test(s)) return null;
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

/**
 * parseShorthand — convert a user-typed shorthand string to a number.
 *
 * Rules (applied in order):
 *   1. Trim and lowercase.
 *   2. Strip leading currency symbol ($, €, £, ¥, ₹, ₿).
 *   3. If wrapped in parens "(N)" → mark negative, strip parens.
 *   4. Strip thousands separators (commas, spaces, narrow-spaces, ').
 *   5. If suffix is "bps" → parse leading number, multiply by 0.0001.
 *   6. If suffix is "%" → parse leading number, divide by 100 (default).
 *   7. If suffix is k/m/b/t → multiply by SI factor.
 *   8. Otherwise parseFloat the remainder.
 *   9. Return null if any step yields NaN or empty.
 */
export function parseShorthand(
  input: string | number | null | undefined,
  options?: ShorthandOptions,
): number | null {
  // Coerce numeric pass-through — caller may pre-validate.
  if (typeof input === "number") {
    return Number.isFinite(input) ? input : null;
  }
  if (input === null || input === undefined) return null;

  const opts = { ...DEFAULT_OPTIONS, ...options };

  // Step 1: trim + lowercase.
  let s = String(input).trim().toLowerCase();
  if (s === "") return null;

  // Step 2: parens → negative (accounting convention). Strip BEFORE currency so
  // patterns like "($1.5m)" → "$1.5m" → strip $ next.
  let negate = false;
  if (s.startsWith("(") && s.endsWith(")")) {
    negate = true;
    s = s.slice(1, -1).trim();
  }

  // Step 3: strip currency symbols (single leading char). Run TWICE bracketing
  // sign-strip so inputs like "-$100" (sign before currency) AND "$-100"
  // (currency before sign — rare but seen in pasted Excel data) both work.
  s = s.replace(/^[$€£¥₹₿]/u, "");

  // Allow leading +/- sign after first currency strip.
  let signMul = 1;
  if (s.startsWith("+")) {
    s = s.slice(1);
  } else if (s.startsWith("-")) {
    signMul = -1;
    s = s.slice(1);
  }

  // Trim whitespace that may have been left between sign and currency
  // (e.g. "- $100" → after sign-strip: " $100" → trim → "$100").
  s = s.trimStart();

  // Strip currency symbol AGAIN — handles "-$100" / "- $100" where the dollar
  // arrived after sign-strip. Cheap and idempotent if no currency present.
  s = s.replace(/^[$€£¥₹₿]/u, "");

  // QA iter-2 fix: derive a single `sign` multiplier from `negate` (parens) and
  // `signMul` (leading +/-). When parens are present, they OVERRIDE the inner
  // sign — `(-100)` is non-standard but unambiguously a negative value, NOT
  // a double-negation. The earlier formula
  // `negate ? -out * signMul : out * signMul` flipped to +100 in that case,
  // and so does the naive `(negate ? -1 : 1) * signMul`. The right rule is:
  // parens win.
  //
  //  Input        | negate | signMul | sign | result
  //  -------------|--------|---------|------|-------
  //  (500)        | true   |   +1    |  -1  |  -500
  //  ($1.5m)      | true   |   +1    |  -1  |  -1.5M
  //  (-100)       | true   |   -1    |  -1  |  -100
  //  -100         | false  |   -1    |  -1  |  -100
  //  +100         | false  |   +1    |  +1  |  +100
  //  100          | false  |   +1    |  +1  |  +100
  const sign = negate ? -1 : signMul;

  // Step 4: strip thousands separators (commas, spaces, NBSP, narrow-no-break, apostrophe).
  // WHY include narrow-no-break (U+202F) and NBSP (U+00A0): used as thousands separator
  // in fr-FR / de-CH locales when user pastes from Excel.
  s = s.replace(/[\s,'  ]/gu, "");

  if (s === "") return null;

  // Step 5: basis-points suffix (must check before single-letter "b" billions).
  if (s.endsWith("bps") || s.endsWith("bp")) {
    const numStr = s.replace(/bps?$/u, "");
    const n = strictParseFloat(numStr);
    if (n === null) return null;
    const out = opts.bpsAsFraction ? n * 0.0001 : n;
    return out * sign;
  }

  // Step 6: percent suffix.
  if (s.endsWith("%")) {
    const numStr = s.slice(0, -1);
    const n = strictParseFloat(numStr);
    if (n === null) return null;
    const out = opts.percentAsFraction ? n / 100 : n;
    return out * sign;
  }

  // Step 7: SI suffix (k/m/b/t). Single trailing char.
  const lastChar = s.at(-1);
  if (lastChar && lastChar in SI_MULTIPLIERS) {
    const numStr = s.slice(0, -1);
    const n = strictParseFloat(numStr);
    if (n === null) return null;
    const out = n * (SI_MULTIPLIERS[lastChar] ?? 1);
    return out * sign;
  }

  // Step 8: plain number.
  const n = strictParseFloat(s);
  if (n === null) return null;
  return n * sign;
}

/**
 * formatShorthand — inverse of parseShorthand for *display* in the input.
 *
 * WHY EXISTS: When a user has just typed "1.5m" and tabs out, we want the
 * input to *stay* showing "1.5M" (their mental model) — not flip to
 * "1,500,000" which forces them to re-parse. This formatter rounds to a
 * compact representation when the value is large enough.
 *
 * For values < 1000, returns the raw number. Beyond that, returns SI shorthand.
 * Scientific-notation-safe: very small values (e.g. 1e-7) display as "1e-7"
 * which the parser accepts back losslessly.
 */
export function formatShorthand(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";

  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(decimals).replace(/\.?0+$/, "")}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(decimals).replace(/\.?0+$/, "")}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(decimals).replace(/\.?0+$/, "")}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(decimals).replace(/\.?0+$/, "")}K`;
  // String(value) handles very-small floats correctly: 1e-7 → "1e-7" (not lossy).
  // The parser's STRICT_NUMBER regex accepts the scientific form on round-trip.
  return String(value);
}
