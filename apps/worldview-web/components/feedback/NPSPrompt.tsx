/**
 * components/feedback/NPSPrompt.tsx — full-screen NPS dialog.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-03):
 * NPS = "How likely are you to recommend Worldview to a colleague?" on a
 * 0-10 scale, plus an optional comment. We render it as a modal Dialog
 * so the user must engage or dismiss explicitly — banners and corner
 * toasts get ignored.
 *
 * APPROVED FREQUENCY: 1/quarter/user (PRD-0053 Wave G open question 4).
 * Trigger eligibility lives in `useNPSEligibility`. This component is
 * the dumb renderer; the milestone handler decides when to mount it.
 *
 * SUBMIT FLOW:
 *   1. user picks a score (0..10 grid)
 *   2. optional comment (≤2000 chars per backend MicroSurveyCreate)
 *   3. POST /v1/feedback/nps with { score, comment, surface }
 *   4. on success: markSubmitted() so the cooldown starts
 *   5. on dismiss / Maybe later: markDismissed() so we skip until next quarter
 */

"use client";

import { useCallback, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useNPSEligibility } from "@/hooks/useNPSEligibility";
import { createGateway, GatewayError } from "@/lib/gateway";

// ── Constants ──────────────────────────────────────────────────────────────

const SCORES = Array.from({ length: 11 }, (_, i) => i); // 0..10 inclusive
const MAX_COMMENT_LEN = 2000;

// ── Props ──────────────────────────────────────────────────────────────────

export interface NPSPromptProps {
  /** Controlled open state — parent decides when to mount. */
  open: boolean;
  /** Called when the dialog should close (X clicked, Maybe later, or success). */
  onOpenChange: (open: boolean) => void;
  /**
   * Trigger surface tag for analytics — backend stores it on `nps_score.surface`.
   * Examples: "post_sync", "post_first_alert".
   */
  surface: string;
}

// ── Component ──────────────────────────────────────────────────────────────

export function NPSPrompt({ open, onOpenChange, surface }: NPSPromptProps) {
  const { accessToken } = useAuth();
  const { markSubmitted, markDismissed } = useNPSEligibility();

  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState("");

  const submit = useMutation({
    mutationFn: async (vars: { score: number; comment: string | null }) => {
      return createGateway(accessToken).postNPS({
        score: vars.score,
        comment: vars.comment,
        surface,
      });
    },
    onSuccess: () => {
      markSubmitted();
      // Reset local state for the next time the dialog mounts.
      setScore(null);
      setComment("");
      onOpenChange(false);
    },
  });

  const handleDismiss = useCallback(() => {
    markDismissed();
    onOpenChange(false);
  }, [markDismissed, onOpenChange]);

  const handleSubmit = useCallback(() => {
    if (score === null) return;
    submit.mutate({ score, comment: comment.trim() || null });
  }, [score, comment, submit]);

  // WHY a controlled dialog: we need to call markDismissed() when the user
  // closes via the X button, not just when they press "Maybe later".
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        markDismissed();
      }
      onOpenChange(next);
    },
    [markDismissed, onOpenChange],
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>How are we doing?</DialogTitle>
          <DialogDescription>
            On a scale of 0 to 10, how likely are you to recommend Worldview to a
            colleague? Your answer helps us prioritise.
          </DialogDescription>
        </DialogHeader>

        {/* 0..10 number pad — single row on desktop, scaled down on mobile. */}
        <div
          className="my-2 flex flex-wrap gap-1.5"
          role="radiogroup"
          aria-label="NPS score"
        >
          {SCORES.map((n) => {
            const selected = score === n;
            return (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setScore(n)}
                // WHY tabular-nums + font-mono via class: numeric pads in
                // dense finance UIs always use tabular figures so each
                // glyph is the same width.
                className={[
                  "h-9 w-9 rounded-[2px] border text-sm font-mono tabular-nums transition-colors",
                  selected
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card hover:bg-muted",
                ].join(" ")}
              >
                {n}
              </button>
            );
          })}
        </div>

        {/* Lightweight scale labels per Bain NPS convention. */}
        <div className="mb-2 flex justify-between text-[10px] text-muted-foreground">
          <span>Not likely</span>
          <span>Extremely likely</span>
        </div>

        {/* Optional follow-up. */}
        <label className="block">
          <span className="text-xs text-muted-foreground">Anything we should know? (optional)</span>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value.slice(0, MAX_COMMENT_LEN))}
            rows={3}
            className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="What worked, what didn't, what's missing…"
          />
          <span className="mt-1 block text-right text-[10px] tabular-nums text-muted-foreground">
            {comment.length} / {MAX_COMMENT_LEN}
          </span>
        </label>

        {submit.isError && (
          <p className="text-xs text-destructive" role="alert">
            {submit.error instanceof GatewayError
              ? submit.error.message
              : "Submit failed — please retry."}
          </p>
        )}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="ghost" onClick={handleDismiss}>
            Maybe later
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={score === null || submit.isPending}
          >
            {submit.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Submit
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
