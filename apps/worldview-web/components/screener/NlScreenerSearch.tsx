/**
 * components/screener/NlScreenerSearch.tsx — natural-language screen builder.
 *
 * WHY THIS EXISTS (PLAN-0091, Bloomberg-competitive vision):
 *   The backend POST /v1/screener/nl-translate turns plain English ("large-cap
 *   tech under 20x earnings with a dividend") into structured screener filters.
 *   Bloomberg EQS has NO natural-language screen builder — surfacing this as a
 *   first-class input is a concrete edge. This component is the UI for it.
 *
 * HOW IT WORKS:
 *   1. User types a prompt and submits (Enter or the arrow button).
 *   2. useNlScreenerTranslate posts to the backend and returns ScreenerFilter[].
 *   3. We map those back to a FilterState (nlFiltersToFilterState) and call
 *      onApply — which flows through the page's NORMAL apply pipeline, so the
 *      result shows up in the chip strip, is editable, and is saveable.
 *
 * WHY map → FilterState (not apply raw filters): keeps a SINGLE source of truth
 * for "the current screen" (FilterState). An NL screen is then indistinguishable
 * from a hand-built one — the user can tweak it, save it, or reset it normally.
 *
 * ERROR / EMPTY HANDLING:
 *   - Pending: input + button disabled, button shows a spinner glyph.
 *   - Backend error: a designed <ScreenerAlert variant="error"> callout with the
 *     error text (roadmap #6b — was a bare red <p>, which read as a crash).
 *   - Zero filters understood: a soft <ScreenerAlert variant="warning"> hint
 *     (the query ran but produced no constraints) — we do NOT apply an empty
 *     screen silently.
 */

"use client";

import { useState } from "react";
import { Sparkles, ArrowRight, Loader2 } from "lucide-react";
import { useNlScreenerTranslate } from "@/hooks/useNlScreenerTranslate";
import { nlFiltersToFilterState } from "@/features/screener/lib/build-filters";
import type { FilterState } from "@/features/screener/lib/filter-state";
import { cn } from "@/lib/utils";
// #6b (roadmap A3): surface NL failures as a designed Alert callout instead of a
// bare line of red text. ScreenerAlert is a screener-local bordered/icon-led
// component (no shared components/ui Alert exists).
import { ScreenerAlert } from "@/components/screener/ScreenerAlert";

export interface NlScreenerSearchProps {
  /**
   * Apply handler — same one the presets / chip strip use. Receives the
   * FilterState mapped from the NL-translate result.
   */
  onApply: (filters: FilterState) => void;
}

export function NlScreenerSearch({ onApply }: NlScreenerSearchProps) {
  const [query, setQuery] = useState("");
  // `noConstraints` flags the "query ran but produced no filters" case so we can
  // show a hint without treating it as a hard error. Cleared on every new submit.
  const [noConstraints, setNoConstraints] = useState(false);

  const translate = useNlScreenerTranslate();

  function handleSubmit() {
    const trimmed = query.trim();
    if (!trimmed || translate.isPending) return;
    setNoConstraints(false);
    translate.mutate(trimmed, {
      onSuccess: (result) => {
        if (!result.filters || result.filters.length === 0) {
          // The backend understood the request but extracted no constraints —
          // don't blow away the user's current screen with an empty one.
          setNoConstraints(true);
          return;
        }
        onApply(nlFiltersToFilterState(result.filters));
      },
      // onError is surfaced via translate.error below — no extra handling needed.
    });
  }

  return (
    <div className="flex flex-col gap-1 border-b border-border px-2 py-1.5">
      <div className="flex items-center gap-1.5">
        {/* Sparkles glyph cues "AI/NL feature" without spending horizontal space
            on a text label — the placeholder carries the affordance copy. */}
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden strokeWidth={1.5} />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          // WHY Enter-to-submit: an NL prompt is a single-line query; Enter is the
          // expected commit gesture (matches a search box, not a textarea).
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSubmit();
            }
          }}
          disabled={translate.isPending}
          aria-label="Describe your screen in plain English"
          placeholder="Describe a screen — e.g. “large-cap tech under 20x P/E with a dividend”"
          className="h-7 flex-1 bg-card border border-border rounded-[2px] px-2 text-[11px] font-mono text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={translate.isPending || query.trim().length === 0}
          aria-label="Translate and apply natural-language screen"
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-[2px] border transition-colors",
            "bg-primary/10 border-primary/60 text-primary hover:bg-primary/20",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {translate.isPending ? (
            // WHY animate-spin here (allowed): this is a sub-second IN-FLIGHT
            // spinner on an explicit user action, not a skeleton placeholder —
            // the §6.2 animate-pulse ban applies to loading skeletons, not action
            // spinners.
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden strokeWidth={1.5} />
          ) : (
            <ArrowRight className="h-3.5 w-3.5" aria-hidden strokeWidth={1.5} />
          )}
        </button>
      </div>

      {/* Error: backend failed (network / 5xx / LLM error). Wrapped in a
          designed Alert (bordered + icon) so it reads as a handled state, not a
          raw stack-trace tell (roadmap #6b). */}
      {translate.isError && (
        <ScreenerAlert variant="error">
          Couldn&apos;t translate that screen — {translate.error.message}
        </ScreenerAlert>
      )}

      {/* Soft hint: the query ran but no filters were extracted. */}
      {noConstraints && !translate.isError && (
        <ScreenerAlert variant="warning">
          Couldn&apos;t interpret that into filters — try naming a metric (P/E,
          market cap, dividend yield, sector…).
        </ScreenerAlert>
      )}

      {/* Explanation echo (if the backend returned one) — builds trust by showing
          how the prompt was interpreted. */}
      {translate.data?.explanation && !noConstraints && !translate.isError && (
        <p className="px-1 text-[10px] font-mono text-muted-foreground">
          {translate.data.explanation}
        </p>
      )}
    </div>
  );
}
