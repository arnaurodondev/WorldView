/**
 * hooks/useFeedbackSubmit.ts — TanStack mutation wrapper for POST /v1/feedback/submissions.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-02):
 * The FeedbackModal needs a single async submit primitive that:
 *   1. validates the payload locally (length bounds matching the backend
 *      Pydantic schema) before hitting the network — saves a round-trip
 *      and lets the form surface field-level errors faster
 *   2. forwards the typed payload through the gateway client
 *   3. exposes loading + error state so the UI can disable the submit button
 *      and show a redacted error message (the GatewayError detail)
 *
 * WHY THIN WRAPPER OVER useMutation: every other component in the app uses
 * createGateway directly inside useMutation. We extract this hook because
 * Wave G has THREE entry points (FeedbackModal, FeedbackButton, future
 * embed widget) all submitting feedback — DRY-ing the validation + token
 * plumbing in one place avoids drift.
 *
 * VALIDATION RULES (must mirror feedback_schemas.FeedbackSubmissionCreate):
 *   - description: 10-5000 chars
 *   - email: any non-empty string when user is anon; backend re-validates
 *   - screenshot_url: https-only (backend rejects javascript: / data:)
 * The backend is the source of truth — these checks are UX-only.
 */

"use client";
// WHY "use client": React hook surface + uses createGateway with a token
// from React state. Server components cannot consume React Query.

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createGateway, GatewayError } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type {
  FeedbackSubmission,
  FeedbackSubmissionPayload,
} from "@/types/api";

// ── Validation ─────────────────────────────────────────────────────────────

/**
 * Local validation error — surfaces to the form before the network call.
 * `field` matches the payload key for inline highlighting.
 */
export class FeedbackValidationError extends Error {
  constructor(public readonly field: keyof FeedbackSubmissionPayload, message: string) {
    super(message);
    this.name = "FeedbackValidationError";
  }
}

/**
 * validate — runs the same length checks as the backend Pydantic model.
 *
 * WHY local validation in addition to the backend Pydantic check: the
 * backend returns a 422 with a generic detail; the user gets a faster +
 * field-aware error if we catch it client-side. The backend is the source
 * of truth — if it 422s on a value we accepted, we surface the message.
 */
function validate(payload: FeedbackSubmissionPayload, isAuthenticated: boolean): void {
  // 10..5000 chars per FeedbackSubmissionCreate.description Field()
  const descLen = payload.description?.trim().length ?? 0;
  if (descLen < 10) {
    throw new FeedbackValidationError(
      "description",
      "Please provide at least 10 characters of detail.",
    );
  }
  if (descLen > 5000) {
    throw new FeedbackValidationError(
      "description",
      "Description must be 5000 characters or fewer.",
    );
  }
  // Anonymous flow: backend requires an email when no JWT user is present.
  if (!isAuthenticated && (!payload.email || payload.email.trim().length === 0)) {
    throw new FeedbackValidationError(
      "email",
      "Email is required when submitting without an account.",
    );
  }
  // screenshot_url scheme check — backend rejects non-https.
  if (payload.screenshot_url) {
    try {
      const url = new URL(payload.screenshot_url);
      if (url.protocol !== "https:") {
        throw new FeedbackValidationError(
          "screenshot_url",
          "Screenshot URL must be https.",
        );
      }
    } catch (err) {
      // URL constructor throws TypeError for invalid URLs.
      if (err instanceof FeedbackValidationError) throw err;
      throw new FeedbackValidationError(
        "screenshot_url",
        "Invalid screenshot URL.",
      );
    }
  }
}

// ── Hook ───────────────────────────────────────────────────────────────────

/**
 * useFeedbackSubmit — returns a useMutation result for posting feedback.
 *
 * Usage:
 *   const submit = useFeedbackSubmit();
 *   submit.mutate(payload, { onSuccess: () => closeModal() });
 *
 * The form should:
 *   - read submit.isPending to disable the submit button
 *   - read submit.error to show a banner — it can be a
 *     FeedbackValidationError (local) or a GatewayError (server)
 */
export function useFeedbackSubmit() {
  const { accessToken, isAuthenticated } = useAuth();
  const queryClient = useQueryClient();

  return useMutation<FeedbackSubmission, Error, FeedbackSubmissionPayload>({
    mutationFn: async (payload) => {
      // WHY validate inside mutationFn (not in onMutate): TanStack treats
      // a thrown mutationFn as the canonical error path. onMutate is for
      // optimistic updates and any throw there is silently swallowed in
      // some versions. mutationFn errors land cleanly in mutation.error.
      validate(payload, isAuthenticated);
      return createGateway(accessToken).postFeedbackSubmission(payload);
    },
    // WHY retry only on 5xx/network (not validation): FeedbackValidationError is
    // thrown before the network call and will never resolve on retry. GatewayError
    // with status < 500 (4xx) is a deterministic rejection — no point retrying.
    // Only transient 5xx/network failures benefit from exponential backoff.
    retry: (count: number, err: Error) => {
      if (err instanceof FeedbackValidationError) return false;
      if (err instanceof GatewayError && err.status < 500) return false;
      return count < 3;
    },
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: () => {
      // Invalidate the user's own list so a "My submissions" surface
      // (future) refreshes. Use a broad key prefix to catch any active
      // user-list query regardless of filter args.
      void queryClient.invalidateQueries({ queryKey: ["feedback-submissions"] });
    },
  });
}

/**
 * formatSubmitError — converts a GatewayError / FeedbackValidationError
 * into a user-facing string. UI components import this so error display
 * is consistent across FeedbackModal and any embedded forms.
 */
export function formatSubmitError(err: unknown): string {
  if (err instanceof FeedbackValidationError) return err.message;
  if (err instanceof GatewayError) {
    // 422 detail is the most useful — Pydantic returns specific field errors.
    if (err.status === 422) return err.message || "Invalid submission.";
    if (err.status === 401) return "Sign in or provide an email to submit feedback.";
    if (err.status >= 500) return "Server error — please retry in a moment.";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Unknown error.";
}
