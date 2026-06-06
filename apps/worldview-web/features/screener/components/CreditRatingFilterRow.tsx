"use client";

/**
 * features/screener/components/CreditRatingFilterRow.tsx — Credit-rating
 * multi-select filter row (PRD-0089 Wave I-B Block IB-L2, T-IB-07).
 *
 * WHY THIS EXISTS: Wave L-2 backend (commit e1a0193f) added a
 * `credit_ratings: list[str]` field to `ScreenFilterRequest`. Unlike country
 * / exchange (Wave L-1 scalar string), this field natively accepts an IN
 * list — so the frontend can send the full multi-select array end-to-end
 * with no truncation disclosure required.
 *
 * WHY a dedicated component (not inline in ScreenerFilterBar): consistent
 * with the IB-L1 pattern (CountryFilterRow / ExchangeFilterRow). Keeps the
 * 808-LOC ScreenerFilterBar from sprawling further and lets Vitest exercise
 * the row in isolation.
 *
 * WHY MultiCombobox (not native <select multiple>): the country / exchange
 * rows use MultiCombobox. Using the same widget here gives users one
 * predictable multi-select interaction throughout the popover.
 *
 * WHY NO BackendPendingBadge: Wave L-2 backend shipped 2026-05-27 — the
 * field is live. No "coming soon" indicator needed.
 *
 * WHY NO truncation badge (unlike CountryFilterRow's "backend: 1 of N"):
 * `credit_ratings` is a List[str] in the backend Pydantic model and is
 * applied as `WHERE snap.credit_rating IN (:list)` (see
 * fundamental_metrics_query.py:340). Every selected rating reaches the
 * database — no silent first-entry truncation.
 */

import { MultiCombobox, type MultiComboboxItem } from "@/components/ui/multi-combobox";
import { CREDIT_RATING_VALUES, creditRatingTone } from "@/lib/screener/credit-rating";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface CreditRatingFilterRowProps {
  /** Current selection — array of rating strings (e.g. ["AA-", "A+"]). */
  value: readonly string[];
  /** Called with the new selection. Empty array = clear filter. */
  onChange: (ratings: string[]) => void;
}

// ── Static option list ────────────────────────────────────────────────────────

// WHY pre-compute (not memoise per-render): the rating ladder is a closed,
// static set of 22 values. A module-level constant avoids the small cost of
// rebuilding the array on every render of the FilterBar.
const RATING_OPTIONS: MultiComboboxItem[] = CREDIT_RATING_VALUES.map((rating) => ({
  id: rating,
  label: rating,
}));

// ── Component ─────────────────────────────────────────────────────────────────

export function CreditRatingFilterRow({ value, onChange }: CreditRatingFilterRowProps) {
  // WHY render the active selection as tinted chips next to the combobox: the
  // combobox UI shows "3 selected" but the user wants to see WHICH ratings
  // they picked at a glance. Each chip uses the same tone as the badge column
  // (creditRatingTone) so the visual mapping is consistent across the page.
  // We render up to 6 chips inline; the rest are folded into "+N" — past 6
  // the user can clear & restart faster than reading them all.
  const MAX_INLINE_CHIPS = 6;
  const visibleChips = value.slice(0, MAX_INLINE_CHIPS);
  const overflow = value.length - visibleChips.length;

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <label className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-20 shrink-0">
        Credit
      </label>

      {/* ── Active rating chips (tone-tinted) ───────────────────────────
        * WHY tinted (not plain): the colour communicates the tier — green
        * for investment grade, amber for speculative, red for distressed —
        * even when the user hasn't opened the cell-renderer column. */}
      {visibleChips.length > 0 && (
        <div
          className="flex items-center gap-1 flex-wrap"
          role="group"
          aria-label="Selected credit ratings"
        >
          {visibleChips.map((rating) => {
            const tone = creditRatingTone(rating);
            // Same explicit-class approach as the cell renderer — Tailwind
            // JIT can't resolve `text-${tone}` strings dynamically.
            // WHY include "muted" branch (QA #3): the helper's tone union now
            // includes "muted" for null/empty input. CREDIT_RATING_VALUES is
            // a closed list of real ratings (never null/empty), so this branch
            // is unreachable in practice — but listing it keeps the mapping
            // exhaustive and matches the cell-renderer's defensive pattern.
            const toneClass =
              tone === "positive"
                ? "bg-positive/10 text-positive border-positive/40"
                : tone === "warning"
                  ? "bg-warning/10 text-warning border-warning/40"
                  : tone === "negative"
                    ? "bg-negative/10 text-negative border-negative/40"
                    : "text-muted-foreground border-muted-foreground/40";
            return (
              <span
                key={rating}
                className={cn(
                  "inline-flex items-center justify-center text-[9px] font-mono px-1 border rounded-[2px]",
                  toneClass,
                )}
              >
                {rating}
              </span>
            );
          })}
          {overflow > 0 && (
            <span className="text-[9px] font-mono text-muted-foreground px-1">
              +{overflow}
            </span>
          )}
        </div>
      )}

      {/* ── Multi-select combobox ───────────────────────────────────────
        * WHY a 36-row dropdown is fine: the rating ladder is exactly 22
        * values, ordered worst→best. No virtualisation needed; the
        * combobox renders the list with a simple max-h overflow. */}
      <MultiCombobox
        items={RATING_OPTIONS}
        selectedIds={[...value]}
        onChange={onChange}
        placeholder="All ratings"
        emptyMessage="No matching ratings."
        className="h-7 w-44"
      />
    </div>
  );
}
