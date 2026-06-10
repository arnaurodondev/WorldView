/**
 * features/chat/components/FollowUpChips.tsx — Per-answer follow-up suggestions.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block C, T-13):
 *   TradingView, Perplexity Finance, and Bloomberg's GPT chat surface 2–4
 *   "next question" chips under every well-cited assistant answer. The
 *   pattern measurably reduces analyst friction: instead of typing a
 *   follow-up, the analyst clicks the chip and the composer sends. T-13
 *   is the presentation half of that pattern — the suggestion strings
 *   themselves are derived elsewhere (T-07 `MessageTurn` or page-level
 *   logic, depending on which signals are available). This component
 *   stays pure: take an array of suggestion strings, render dense chips,
 *   call `onPick(suggestion)` on click.
 *
 *   Design rule: 2 to 4 chips. Below 2 we render nothing (not enough to
 *   justify the row); above 4 we hard-cap (rendering 7 chips creates a
 *   wall of text that defeats the dense-UI intent). The caller is
 *   expected to pre-trim — we still clamp defensively.
 *
 * DATA SOURCE: pure prop — caller passes the suggestions array. No fetch.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5 (follow-up chips
 *   under each assistant turn) + design system Tier-1 chrome (no
 *   animation; instant click feedback only).
 */

interface FollowUpChipsProps {
  /**
   * Suggestion strings to render. The component clamps the list to the
   * first 4 entries and renders nothing if fewer than 2 are supplied.
   */
  readonly suggestions: string[];
  /**
   * Click handler — receives the exact suggestion string. The caller is
   * expected to seed the chat composer and send immediately (TradingView
   * pattern) but the chip stays neutral about that policy.
   */
  readonly onPick: (suggestion: string) => void;
  /**
   * Accessible name for the chip list (Round 3). Default keeps the original
   * "Follow-up suggestions" so existing call sites + tests are unchanged;
   * the empty-conversation welcome re-uses this presenter with
   * "Starter prompts" so screen readers don't announce starters as
   * follow-ups to an answer that doesn't exist yet.
   */
  readonly ariaLabel?: string;
}

// Lower / upper bounds per design §5. Under 2 we render null; over 4 we
// clamp. Centralised so the unit test (T-22) can assert against the same
// constants instead of duplicating the numbers.
const MIN_CHIPS = 2;
const MAX_CHIPS = 4;

/**
 * FollowUpChips — see file header. Renders nothing when the suggestion
 * array is too short, otherwise emits one `<button>` per suggestion.
 * Each chip carries `data-cell` so the Wave K density e2e (T-23) counts
 * them toward the above-fold cell budget.
 */
export function FollowUpChips({
  suggestions,
  onPick,
  ariaLabel = "Follow-up suggestions",
}: FollowUpChipsProps) {
  if (suggestions.length < MIN_CHIPS) return null;
  // slice() is safe with `n > length` — returns the whole array.
  const visible = suggestions.slice(0, MAX_CHIPS);

  return (
    <div
      className="mt-1 flex flex-wrap gap-1"
      role="list"
      aria-label={ariaLabel}
    >
      {visible.map((suggestion, idx) => (
        <button
          key={`${idx}-${suggestion}`}
          type="button"
          data-cell
          // tabular-nums is mostly cosmetic here (the chip text is
          // English) but it keeps any numbers inside a suggestion
          // (e.g. "P/E ratio of 24") aligned with the rest of the chat.
          // Round 3 polish: hover → bg-muted (the sprint's canonical chip
          // hover, was bg-muted/40) and an explicit :focus-visible ring so
          // keyboard users tabbing through chips see exactly where they are
          // (native button outline is suppressed for the custom ring).
          className="border border-border bg-card px-2 py-0.5 text-[10px] font-mono tabular-nums text-foreground hover:bg-muted hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary transition-color-only duration-75"
          onClick={() => onPick(suggestion)}
          title={suggestion}
        >
          {suggestion}
        </button>
      ))}
    </div>
  );
}
