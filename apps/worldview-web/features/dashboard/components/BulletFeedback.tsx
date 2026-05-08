/**
 * features/dashboard/components/BulletFeedback.tsx — per-bullet thumbs feedback
 * (PLAN-0066 Wave F T-W10-F-03).
 *
 * WHY THIS EXISTS: Inline thumbs up/down on each brief bullet creates a granular
 * signal dataset for future LLM fine-tuning. A bullet rated "unhelpful" by many
 * users reveals where the briefing model is generating low-quality or irrelevant
 * claims.
 *
 * WHY HOVER-ONLY (opacity-0 group-hover:opacity-100):
 * Brief bullets are dense text in a small card. Showing feedback buttons on every
 * bullet at all times would be visually noisy — they'd compete with the content.
 * Revealing on hover follows the Bloomberg/Refinitiv convention for inline micro-
 * actions: available but unobtrusive.
 *
 * WHY OPTIMISTIC UPDATE:
 * Feedback is best-effort (no retry, silent failure on network error). The UI fills
 * the icon immediately on click so the trader gets instant acknowledgement. If the
 * POST fails silently, the filled icon remains (no rollback) — this is intentional
 * because: (a) the trader has already moved on, (b) reverting an icon they just
 * clicked would be confusing, (c) one lost feedback row is acceptable data loss.
 *
 * WHO USES IT: StructuredBrief (passed down via briefId optional prop).
 * DATA SOURCE: POST /api/v1/briefings/feedback/bullet (S8 via S9 proxy)
 */

"use client";
// WHY "use client": useState for optimistic selection, async POST on click.

import { useState } from "react";
import { postBulletFeedback } from "@/lib/api/briefing";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BulletFeedbackProps {
  /** Auth token from the parent that owns useAuth(). */
  token: string | undefined;
  /** UUID of the brief — sent in the POST body to tie feedback to the brief. */
  briefId: string;
  /** 0-based section index (identifies which section the bullet belongs to). */
  sectionIdx: number;
  /** 0-based bullet index within the section. */
  bulletIdx: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BulletFeedback({ token, briefId, sectionIdx, bulletIdx }: BulletFeedbackProps) {
  // WHY null initial state: no selection means neither button is filled.
  // Once selected, the icon stays filled (optimistic) even if the POST fails.
  const [selected, setSelected] = useState<"helpful" | "unhelpful" | null>(null);

  const submit = async (reaction: "helpful" | "unhelpful") => {
    // WHY idempotent guard: if the trader double-clicks, we don't re-send the POST.
    if (selected !== null) return;
    // WHY optimistic before await: fills the icon immediately for instant feedback.
    setSelected(reaction);
    try {
      await postBulletFeedback(token, briefId, sectionIdx, bulletIdx, reaction);
    } catch {
      // WHY silent failure: see component doc above.
      // The filled icon remains (optimistic state is intentionally NOT rolled back).
    }
  };

  return (
    // WHY inline-flex: renders horizontally inline after the bullet text.
    // opacity-0 group-hover:opacity-100: hidden at rest, revealed on hover.
    // WHY transition-opacity: smooth reveal matches Bloomberg's micro-action UX.
    // The parent <li> must have the "group" class for this to work.
    <span
      className="inline-flex items-center gap-1 ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
      data-testid="bullet-feedback"
    >
      {/* Thumbs-up button */}
      <button
        onClick={() => void submit("helpful")}
        disabled={selected !== null}
        aria-label="Mark this bullet as helpful"
        aria-pressed={selected === "helpful"}
        // WHY text-green-400 when selected: green = positive signal, consistent
        // with the diff panel's "new bullet" colour.
        className={
          selected === "helpful"
            ? "text-green-400 cursor-default"
            : "text-muted-foreground hover:text-green-400 transition-colors cursor-pointer"
        }
      >
        {/* WHY Unicode arrows (not Lucide icons): avoids a Lucide import in this
            small feedback component. The up/down triangle convention is universally
            understood for voting/feedback. */}
        {selected === "helpful" ? "▲" : "△"}
      </button>

      {/* Thumbs-down button */}
      <button
        onClick={() => void submit("unhelpful")}
        disabled={selected !== null}
        aria-label="Mark this bullet as unhelpful"
        aria-pressed={selected === "unhelpful"}
        // WHY text-red-400 when selected: red = negative signal, consistent with
        // change_pct negative values elsewhere in the terminal.
        className={
          selected === "unhelpful"
            ? "text-red-400 cursor-default"
            : "text-muted-foreground hover:text-red-400 transition-colors cursor-pointer"
        }
      >
        {selected === "unhelpful" ? "▼" : "▽"}
      </button>
    </span>
  );
}
