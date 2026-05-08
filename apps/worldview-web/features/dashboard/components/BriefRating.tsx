/**
 * features/dashboard/components/BriefRating.tsx — brief-level 5-star rating
 * (PLAN-0066 Wave F T-W10-F-03).
 *
 * WHY THIS EXISTS: A brief-level rating gives a coarser signal than per-bullet
 * feedback — "this brief was generally useful today" vs "this specific bullet
 * was wrong". Both signals together create a richer training dataset for
 * improving the morning briefing LLM prompt over time.
 *
 * WHY 5 STARS (not thumbs): a 5-point Likert scale captures the degree of
 * satisfaction (great vs. okay vs. poor) that a binary thumbs can't express.
 * This matches standard survey UX conventions traders recognise from tools like
 * Refinitiv Workspace's "rate this briefing" panels.
 *
 * WHY OPTIMISTIC + SILENT FAILURE: same rationale as BulletFeedback — feedback
 * is best-effort; rolling back the selected state would be confusing.
 *
 * WHO USES IT: MorningBriefCard expanded view (rendered at the bottom of the brief).
 * DATA SOURCE: POST /api/v1/briefings/feedback/brief (S8 via S9 proxy)
 */

"use client";
// WHY "use client": useState for optimistic star selection.

import { useState } from "react";
import { postBriefRating } from "@/lib/api/briefing";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BriefRatingProps {
  /** Auth token from the parent that owns useAuth(). */
  token: string | undefined;
  /** UUID of the brief being rated. */
  briefId: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/** Star values — used to render 5 buttons and build the POST body */
const STARS = [1, 2, 3, 4, 5] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function BriefRating({ token, briefId }: BriefRatingProps) {
  // WHY null: no star selected initially. Once selected, the rating is fixed
  // (optimistic, same pattern as BulletFeedback).
  const [selected, setSelected] = useState<number | null>(null);

  const submit = async (stars: number) => {
    // WHY idempotent guard: prevent re-submission if the user clicks a second star.
    if (selected !== null) return;
    setSelected(stars); // optimistic fill
    try {
      // WHY cast to string literal type: postBriefRating expects "1"|"2"|...|"5"
      // (matching the S8 Pydantic Literal). String(stars) converts the number safely.
      await postBriefRating(token, briefId, String(stars) as "1" | "2" | "3" | "4" | "5");
    } catch {
      // WHY silent failure: see component doc above.
    }
  };

  return (
    <div className="flex items-center gap-1" data-testid="brief-rating">
      {/* WHY small label: lets the trader know what the stars represent without
          dedicating a lot of visual weight to the rating UI. */}
      <span className="text-[9px] text-muted-foreground/60 mr-1">Rate brief:</span>

      {STARS.map((s) => (
        <button
          key={s}
          onClick={() => void submit(s)}
          disabled={selected !== null}
          aria-label={`Rate brief ${s} star${s > 1 ? "s" : ""}`}
          aria-pressed={selected !== null && s <= selected}
          // WHY filled (text-amber-400) for all stars ≤ selected:
          // Standard 5-star convention — clicking "3" fills stars 1, 2, and 3.
          // WHY hover highlights all stars ≤ hovered: not implemented here
          // (kept simple since hover state adds complexity for minor UX gain).
          className={
            selected !== null && s <= selected
              ? "text-amber-400 cursor-default text-[13px]"
              : "text-muted-foreground/40 hover:text-amber-400 transition-colors cursor-pointer text-[13px]"
          }
        >
          {/* WHY Unicode star (not Lucide Star icon): avoids an extra icon import
              for a very simple shape. The filled/unfilled distinction is handled
              via colour (text-amber-400 vs muted) rather than two separate SVGs. */}
          {selected !== null && s <= selected ? "★" : "☆"}
        </button>
      ))}

      {/* WHY confirmation message: after rating, replace the stars with a brief
          confirmation so the trader knows their rating was received. */}
      {selected !== null && (
        <span className="ml-1 text-[9px] text-muted-foreground/60">Thanks!</span>
      )}
    </div>
  );
}
