/**
 * lib/screener/credit-rating.ts — Credit-rating → color-tone helper
 * (PRD-0089 Wave I-B Block IB-L2, T-IB-07).
 *
 * WHY THIS EXISTS:
 *   The screener now surfaces an `instrument_fundamentals_snapshot.credit_rating`
 *   value from Wave L-2 (e.g. "AA+", "BBB-", "CCC"). For institutional UX, a
 *   raw string isn't enough — credit analysts read a rating as a tier signal:
 *     - INVESTMENT GRADE (AAA…BBB-)  → positive (green) — safe to hold
 *     - JUNK SPECULATIVE  (BB+…BB-)  → warning (amber)  — heightened risk
 *     - JUNK DEEP         (B+ and below + C/D) → negative (red) — distressed
 *   The helper maps a rating string to one of the Terminal Dark semantic
 *   tones so a single source of truth governs both the badge column cell
 *   colour AND any future filter chip / tooltip use.
 *
 * WHY a separate file (not co-located in ag-screener-columns.tsx):
 *   - Unit-testable in isolation without mounting React.
 *   - Re-used by the credit-rating filter row in `ScreenerFilterBar.tsx`
 *     (to colour the active-selection chips) when Wave L-2 lands the
 *     CreditRatingFilterRow.
 *
 * WHY the boundaries land where they do (BBB- is positive, BB+ is warning):
 *   The S&P / Moody's "investment grade" cutoff is BBB- (S&P) / Baa3 (Moody's).
 *   Anything BB+ and below is officially "speculative / junk". This matches
 *   the conventional institutional UX where holdings below BBB- need
 *   compliance approval. We anchor the lower warning bound at B- because
 *   below that the issuer is in or near default — straight to negative.
 *
 * SOURCE: S&P long-term issuer ratings — the same scale EODHD uses for
 *   `general.LongTermDebt` → `credit_rating` snapshot column.
 */

/**
 * CreditRatingTone — the three Terminal Dark semantic tones used by the
 * helper. Returning a union (not a Tailwind class string directly) lets the
 * caller compose `text-${tone}` / `bg-${tone}/10` themselves, avoiding
 * Tailwind's purge-detection pitfall with dynamic class names.
 */
export type CreditRatingTone = "positive" | "warning" | "negative";

// WHY a frozen Set (not an Array): O(1) membership check inside the
// hot-path cell renderer. The set is closed (no future ratings); freezing
// guards against accidental mutation by another module that imports it.
const _INVESTMENT_GRADE: ReadonlySet<string> = Object.freeze(
  new Set<string>([
    "AAA",
    "AA+", "AA", "AA-",
    "A+",  "A",  "A-",
    "BBB+", "BBB", "BBB-",
  ]),
);

// WHY explicit listing (not "starts with BB"): the rating "B+" is below BB-
// and must map to negative, NOT warning. A "starts-with" test would
// incorrectly group B+ into warning. Listing each rung removes the trap.
const _SPECULATIVE_GRADE: ReadonlySet<string> = Object.freeze(
  new Set<string>([
    "BB+", "BB", "BB-",
  ]),
);

/**
 * creditRatingTone — map an S&P rating string to a Terminal Dark tone.
 *
 *   "AAA" → "positive"      (top-tier sovereign-equivalent)
 *   "AA-" → "positive"
 *   "BBB-" → "positive"     (lowest investment grade — boundary)
 *   "BB+" → "warning"       (top of speculative grade — boundary)
 *   "BB-" → "warning"
 *   "B+"  → "negative"      (deep junk — boundary)
 *   "CCC" → "negative"
 *   "D"   → "negative"      (default)
 *
 * Unknown / null / empty input → "negative" (defensive: missing rating is
 * not "no risk" — it's "risk we couldn't classify", which is worse).
 */
export function creditRatingTone(
  rating: string | null | undefined,
): CreditRatingTone {
  if (rating == null) return "negative";
  // WHY trim+toUpperCase: EODHD sometimes returns "aa-" or " AA+ " — normalise.
  const r = rating.trim().toUpperCase();
  if (r === "") return "negative";
  if (_INVESTMENT_GRADE.has(r)) return "positive";
  if (_SPECULATIVE_GRADE.has(r)) return "warning";
  return "negative";
}

/**
 * CREDIT_RATING_VALUES — the discrete set of ratings shown in the
 * credit-rating filter combobox (T-IB-07). Ordered from best to worst so
 * the dropdown reads top-to-bottom like a credit ladder.
 *
 * Exported so the filter row, the active-chips, and the unit tests share
 * one source of truth.
 */
export const CREDIT_RATING_VALUES: readonly string[] = Object.freeze([
  "AAA",
  "AA+", "AA", "AA-",
  "A+",  "A",  "A-",
  "BBB+", "BBB", "BBB-",
  "BB+", "BB", "BB-",
  "B+",  "B",  "B-",
  "CCC+", "CCC", "CCC-",
  "CC",  "C",  "D",
]);
