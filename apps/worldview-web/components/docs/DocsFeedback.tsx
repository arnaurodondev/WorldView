/**
 * components/docs/DocsFeedback.tsx — thumbs feedback widget (T-B-2-08)
 *
 * WHY THIS EXISTS: Thumbs up/down at the bottom of every doc page lets
 * the team find which pages aren't landing. Stripe / Vercel / Tailwind
 * docs all run this widget — it's a low-friction signal channel.
 *
 * WIRING: POSTs to /v1/feedback/micro-survey from PLAN-0052 Wave D
 * (already shipped). The endpoint is tenant-scoped + JWT-gated when
 * authenticated, but accepts anonymous submissions for /docs since the
 * docs hub is publicly indexable.
 *
 * WHY CLIENT COMPONENT: state for the thumbs choice + the "Thanks!"
 * confirmation + the optional comment textarea on thumbs-down.
 */

"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface DocsFeedbackProps {
  /** Path of the docs page being rated (e.g. "/docs/getting-started"). */
  pageUrl: string;
}

type FeedbackChoice = null | "up" | "down";

export function DocsFeedback({ pageUrl }: DocsFeedbackProps) {
  const [choice, setChoice] = useState<FeedbackChoice>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleVote(vote: "up" | "down") {
    setChoice(vote);
    // Thumbs-up has no follow-up form — fire-and-forget the POST.
    if (vote === "up") {
      await postFeedback({ pageUrl, vote, comment: null }).then(
        () => setSubmitted(true),
        () => setSubmitted(true), // soft-fail — don't blame the reader
      );
    }
    // Thumbs-down opens the textarea; submit happens after they hit "Send".
  }

  async function handleSubmitDown() {
    try {
      await postFeedback({ pageUrl, vote: "down", comment });
      setSubmitted(true);
      setError(null);
    } catch (e) {
      // Network error — surface it but keep the form open so user can retry.
      setError(e instanceof Error ? e.message : "Could not send feedback");
    }
  }

  if (submitted) {
    return (
      <div
        role="status"
        className="mt-8 rounded-[2px] border border-positive/30 bg-positive/5 px-4 py-3 text-sm text-foreground"
      >
        Thanks for your feedback. We&apos;ll use it to improve this page.
      </div>
    );
  }

  return (
    <div className="mt-8 rounded-[2px] border border-border/40 bg-card/40 p-4">
      <p className="mb-3 text-xs font-medium text-foreground">
        Was this page helpful?
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Yes, this was helpful"
          aria-pressed={choice === "up"}
          onClick={() => handleVote("up")}
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center rounded-[2px] border transition-colors",
            choice === "up"
              ? "border-positive/40 bg-positive/10 text-positive"
              : "border-border/60 text-muted-foreground hover:border-positive/40 hover:text-positive",
          )}
        >
          <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="No, this was not helpful"
          aria-pressed={choice === "down"}
          onClick={() => handleVote("down")}
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center rounded-[2px] border transition-colors",
            choice === "down"
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : "border-border/60 text-muted-foreground hover:border-destructive/40 hover:text-destructive",
          )}
        >
          <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>

      {choice === "down" ? (
        <div className="mt-3 space-y-2">
          <label
            htmlFor="docs-feedback-comment"
            className="block text-xs text-muted-foreground"
          >
            What was missing or unclear?
          </label>
          <textarea
            id="docs-feedback-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
            maxLength={1000}
            className="w-full rounded-[2px] border border-border/60 bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60"
          />
          {error ? (
            <p className="text-xs text-destructive">{error}</p>
          ) : null}
          <button
            type="button"
            onClick={handleSubmitDown}
            disabled={comment.trim().length === 0}
            // WHY explicit disabled-* tokens (not opacity-50): the
            // disabled-bg/foreground tokens preserve AA contrast for the
            // disabled state instead of dimming the whole button (which
            // can drop below 3:1 against amber). Enforced by
            // __tests__/no-disabled-opacity-50.test.ts.
            className="rounded-[2px] bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))]"
          >
            Send feedback
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * postFeedback — minimal POST to the Wave D micro-survey endpoint.
 * No auth header (docs feedback is anonymous-allowed). Fire-and-forget
 * with explicit error surface so the caller can decide UX response.
 *
 * WHY direct fetch (not the gateway client): docs is a public surface;
 * the auth-aware gateway client adds a JWT header even for anon users,
 * which the backend rejects. Direct fetch keeps the request anonymous.
 */
async function postFeedback(body: {
  pageUrl: string;
  vote: "up" | "down";
  comment: string | null;
}): Promise<void> {
  const res = await fetch("/api/v1/feedback/micro-survey", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      survey_id: "docs-page-helpful",
      // Wave D schema: response is a free-form string. We tag it with
      // up/down + optional comment so the admin dashboard can split.
      response: body.comment
        ? `${body.vote}: ${body.comment}`
        : body.vote,
      context_url: body.pageUrl,
    }),
  });
  if (!res.ok) {
    throw new Error(`Feedback failed (${res.status})`);
  }
}
