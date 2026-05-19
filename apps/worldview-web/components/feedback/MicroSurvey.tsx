/**
 * components/feedback/MicroSurvey.tsx — inline 3-button reaction widget.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-03):
 * Inline micro-surveys are the lowest-friction feedback channel. A single
 * tap (👍 👎 🤷) records sentiment against a survey_key, and we can tag a
 * row with "is this dashboard helpful?" or "did the search find what you
 * needed?" without building a full modal.
 *
 * BACKEND: POST /v1/feedback/micro-survey accepts anonymous calls. The
 * caller passes a `surveyKey` string — uniqueness is on (user_id ∪ tenant
 * fallback, survey_key) so a re-tap updates rather than duplicates.
 */

"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Check, ThumbsDown, ThumbsUp, HelpCircle } from "lucide-react";
import { createGateway, GatewayError } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { SurveyResponse } from "@/types/api";

export interface MicroSurveyProps {
  /** Stable identifier — backend uses (user, key) as uniqueness key. */
  surveyKey: string;
  /** Optional headline — defaults to a generic prompt. */
  prompt?: string;
  /** Optional className passthrough for layout tuning. */
  className?: string;
}

/** Each visible reaction maps to a backend SurveyResponse value + an icon. */
const REACTIONS: Array<{
  value: SurveyResponse;
  Icon: typeof ThumbsUp;
  label: string;
}> = [
  { value: "positive", Icon: ThumbsUp, label: "Helpful" },
  { value: "negative", Icon: ThumbsDown, label: "Not helpful" },
  { value: "neutral", Icon: HelpCircle, label: "Unsure" },
];

export function MicroSurvey({ surveyKey, prompt, className }: MicroSurveyProps) {
  const { accessToken } = useAuth();
  const [picked, setPicked] = useState<SurveyResponse | null>(null);

  const submit = useMutation({
    mutationFn: (response: SurveyResponse) =>
      createGateway(accessToken).postMicroSurvey({
        survey_key: surveyKey,
        response,
      }),
    // WHY retry (CRIT-006 / FR-8.1): postMicroSurvey is an upsert on
    // (user, survey_key) — idempotent. Retry only fires on transient 5xx/network.
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
  });

  const handleClick = (value: SurveyResponse) => {
    if (submit.isPending || picked) return; // single-shot per render
    setPicked(value);
    submit.mutate(value, {
      // WHY rollback on error: keep the UI honest. If the POST fails the
      // user should see the buttons re-enable so they can retry.
      onError: () => setPicked(null),
    });
  };

  // After successful send, show a tiny acknowledgement instead of the buttons.
  if (submit.isSuccess && picked) {
    return (
      <div
        className={[
          "flex items-center gap-1.5 text-xs text-muted-foreground",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        role="status"
      >
        <Check className="h-3.5 w-3.5 text-primary" />
        Thanks for the feedback.
      </div>
    );
  }

  return (
    <div
      className={["flex items-center gap-2", className].filter(Boolean).join(" ")}
      role="group"
      aria-label={prompt ?? "Quick feedback"}
    >
      {prompt && (
        <span className="text-xs text-muted-foreground">{prompt}</span>
      )}
      {REACTIONS.map(({ value, Icon, label }) => (
        <button
          key={value}
          type="button"
          onClick={() => handleClick(value)}
          disabled={submit.isPending || picked !== null}
          aria-label={label}
          className={[
            "rounded-[2px] border border-border bg-card p-1.5 transition-colors hover:bg-muted",
            "disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed",
            picked === value ? "border-primary bg-primary/10" : "",
          ].join(" ")}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ))}
      {submit.isError && (
        <span className="text-[10px] text-destructive" role="alert">
          {submit.error instanceof GatewayError
            ? submit.error.message
            : "Failed."}
        </span>
      )}
    </div>
  );
}
