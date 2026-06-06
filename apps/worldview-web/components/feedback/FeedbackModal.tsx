/**
 * components/feedback/FeedbackModal.tsx — multi-tab feedback Sheet.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-04):
 * Single entry point for ALL feedback flows the user might want:
 *   - Bug Report → kind=bug, severity selector, screenshot + console logs
 *   - Feature Request → kind=feature_request, posts to /v1/feedback/features
 *   - UX/Design → kind=ux (for design issues that aren't bugs)
 *   - General → kind=other (catch-all)
 *   - Contact Us → also kind=other but framed as a support touchpoint
 *
 * SHADCN SHEET (NOT DIALOG): A side-sheet keeps page context visible — the
 * user can reference the very page they're commenting on while typing.
 *
 * AUTO-COLLECTED METADATA (passed silently, no user action needed):
 *   - page_url           — current location.href
 *   - viewport           — width x height (CSS pixels)
 *   - user_agent         — navigator.userAgent (truncated to 512 chars)
 *   - timestamp_utc      — ISO date at submit time
 *   - environment        — process.env.NEXT_PUBLIC_ENV (defaults "production")
 *   - build_hash         — process.env.NEXT_PUBLIC_BUILD_HASH (optional)
 *   - theme              — "dark" (Midnight Pro is the only theme)
 *   - user_role          — JWT role from useAuth (when present)
 * Most of these don't have first-class fields on the backend submission
 * schema; we serialise them into `description` as a hidden footer and
 * also stash structured ones in `console_logs` (Any-typed JSON column).
 */

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useFeedbackSubmit, formatSubmitError } from "@/hooks/useFeedbackSubmit";
import { useConsoleCapture } from "@/hooks/useConsoleCapture";
import { ScreenshotCapture } from "./ScreenshotCapture";
import { ConsoleLogCapture } from "./ConsoleLogCapture";
import { useMutation } from "@tanstack/react-query";
import { createGateway, GatewayError } from "@/lib/gateway";
import type { FeedbackKind, FeedbackSeverity } from "@/types/api";

// ── Tab definitions ────────────────────────────────────────────────────────
//
// WHY a tab tuple (not enum): we need the visual order, the heading text,
// and the backend `kind` mapping all in one place. A const-tuple keeps
// the order deterministic AND lets TypeScript narrow `tab.id`.

type TabId = "bug" | "feature" | "ux" | "general" | "contact";

const TABS: ReadonlyArray<{
  id: TabId;
  label: string;
  /** Maps a tab to the backend `kind` value (some tabs share). */
  kind: FeedbackKind;
}> = [
  { id: "bug", label: "Bug Report", kind: "bug" },
  { id: "feature", label: "Feature Request", kind: "feature_request" },
  { id: "ux", label: "UX/Design", kind: "ux" },
  { id: "general", label: "General", kind: "other" },
  { id: "contact", label: "Contact Us", kind: "other" },
];

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * collectMetadata — gathers everything we know about the current page +
 * client + auth state. Called at submit time so values are fresh.
 */
function collectMetadata(opts: { userRole?: string | null }): Record<string, string | number | undefined> {
  const env = (process.env.NEXT_PUBLIC_ENV as string | undefined) ?? "production";
  const buildHash = (process.env.NEXT_PUBLIC_BUILD_HASH as string | undefined);
  const viewport =
    typeof window !== "undefined"
      ? `${window.innerWidth}x${window.innerHeight}`
      : "unknown";
  const userAgent =
    typeof navigator !== "undefined"
      ? navigator.userAgent.slice(0, 512)
      : undefined;
  const pageUrl =
    typeof window !== "undefined" ? window.location.href : undefined;
  return {
    page_url: pageUrl,
    viewport,
    user_agent: userAgent,
    build_hash: buildHash,
    user_role: opts.userRole ?? undefined,
    timestamp_utc: new Date().toISOString(),
    environment: env,
    theme: "dark", // Midnight Pro is the only theme — no light-mode option.
  };
}

// ── Component ──────────────────────────────────────────────────────────────

export interface FeedbackModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Default tab — useful when launching from "Suggest a feature" CTA. */
  defaultTab?: TabId;
  /**
   * Optional pre-filled description.
   *
   * PLAN-0052 Wave E T-E-5-08: when the modal opens via a deep link
   * (?feedback=bug&page=X), the URL `page` value is folded into the
   * textarea so the user doesn't have to retype context. The user can
   * still edit / clear the text before submitting.
   */
  defaultDescription?: string;
}

export function FeedbackModal({
  open,
  onOpenChange,
  defaultTab = "bug",
  defaultDescription = "",
}: FeedbackModalProps) {
  const { user, isAuthenticated } = useAuth();
  const submitFeedback = useFeedbackSubmit();
  // WHY a separate mutation here: the "feature" tab posts to a different
  // endpoint (POST /v1/feedback/features), not /submissions. Keeping it
  // local avoids polluting useFeedbackSubmit with branch logic.
  const submitFeature = useFeatureSubmit();

  // ── Form state ──────────────────────────────────────────────────────────
  const [tab, setTab] = useState<TabId>(defaultTab);
  const [description, setDescription] = useState(defaultDescription);
  const [severity, setSeverity] = useState<FeedbackSeverity>("medium");
  const [email, setEmail] = useState("");
  const [featureTitle, setFeatureTitle] = useState("");
  const [featureCategory, setFeatureCategory] = useState("");

  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [includeConsole, setIncludeConsole] = useState(false);
  const { logs, clear: clearConsole } = useConsoleCapture(includeConsole);

  // PLAN-0052 Wave E QA-iter1 bugs/M-2: track whether we're currently
  // displaying the prop-supplied prefill. If `defaultDescription` changes
  // WHILE the modal is open AND the user has typed nothing extra, we sync.
  // If the user has started editing (description !== last-seen prefill),
  // we DON'T overwrite their typing. The ref records the prefill we last
  // committed to local state so the comparison is exact rather than
  // heuristic.
  const lastAppliedPrefillRef = useRef<{
    tab: TabId;
    description: string;
  }>({ tab: defaultTab, description: defaultDescription });

  // Reset form when the modal closes — avoids stale state on next open.
  useEffect(() => {
    if (!open) {
      setDescription(defaultDescription);
      setSeverity("medium");
      setEmail("");
      setFeatureTitle("");
      setFeatureCategory("");
      setScreenshotDataUrl(null);
      setIncludeConsole(false);
      clearConsole();
      setTab(defaultTab);
      submitFeedback.reset();
      submitFeature.reset();
      // Refresh the ref so the next open compares against the current
      // prefill, not the last one we showed.
      lastAppliedPrefillRef.current = {
        tab: defaultTab,
        description: defaultDescription,
      };
    } else {
      // PLAN-0052 Wave E T-E-5-08: when the modal opens via a deep-link the
      // parent re-renders with new defaultTab + defaultDescription values.
      // The reset branch above only runs on close → open without re-keying,
      // so we pull the new prefill into local state explicitly here.
      //
      // QA-iter1 bugs/M-2: only overwrite the user's current input if it
      // matches what we last applied — i.e. they haven't started typing.
      // Without this guard, a parent re-render with the same prefill (or
      // a stale render after a deep link) would clobber in-progress text.
      const last = lastAppliedPrefillRef.current;
      if (description === last.description) {
        setDescription(defaultDescription);
      }
      if (tab === last.tab) {
        setTab(defaultTab);
      }
      lastAppliedPrefillRef.current = {
        tab: defaultTab,
        description: defaultDescription,
      };
    }
    // We intentionally exclude submit* and clearConsole from deps to avoid
    // re-running this on every render — they're stable references.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultTab, defaultDescription]);

  const currentTab = TABS.find((t) => t.id === tab)!;

  // ── Submit ──────────────────────────────────────────────────────────────

  const isSubmitting = submitFeedback.isPending || submitFeature.isPending;

  const submitError =
    submitFeedback.error || submitFeature.error
      ? formatSubmitError(submitFeedback.error ?? submitFeature.error)
      : null;

  // user role is not on UserProfile yet — pull from JWT-decoded shape if added later.
  const userRole = (user as unknown as { role?: string } | null)?.role ?? null;

  const handleSubmit = () => {
    const meta = collectMetadata({ userRole });

    if (tab === "feature") {
      // Feature-request branch → /v1/feedback/features.
      submitFeature.mutate(
        {
          title: featureTitle.trim(),
          description: description.trim(),
          category: featureCategory.trim() || null,
        },
        { onSuccess: () => onOpenChange(false) },
      );
      return;
    }

    // All other tabs → /v1/feedback/submissions.
    submitFeedback.mutate(
      {
        kind: currentTab.kind,
        severity: tab === "bug" ? severity : null,
        description: description.trim(),
        email: !isAuthenticated ? email.trim() || null : null,
        page_url: typeof window !== "undefined" ? window.location.href : null,
        user_agent:
          typeof navigator !== "undefined"
            ? navigator.userAgent.slice(0, 512)
            : null,
        // PLAN-0053 QA-iter1 F-003: when the user opts in to a screenshot
        // we now include the full data URI in the JSON ``console_logs`` blob.
        // The backend ``screenshot_url`` column is for HTTPS S3 URLs only;
        // until the presigned-upload route ships, the data URI rides inside
        // the JSON column so it actually reaches operators. Truncate at 1MB
        // to stay within reasonable JSONB row size; html2canvas at default
        // settings produces ~200-500KB so most submissions fit.
        console_logs: {
          metadata: meta,
          console: includeConsole ? logs : null,
          screenshot_data_uri:
            screenshotDataUrl && screenshotDataUrl.length <= 1_048_576
              ? screenshotDataUrl
              : null,
          screenshot_data_uri_truncated:
            screenshotDataUrl !== null && screenshotDataUrl.length > 1_048_576,
        },
      },
      { onSuccess: () => onOpenChange(false) },
    );
  };

  // Disable Submit when the form would fail validation immediately.
  const submitDisabled = useMemo(() => {
    if (isSubmitting) return true;
    if (tab === "feature") {
      return featureTitle.trim().length === 0 || description.trim().length < 1;
    }
    return description.trim().length < 10;
  }, [tab, description, featureTitle, isSubmitting]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {/*
        WHY id on SheetContent: ScreenshotCapture hides this id during the
        html2canvas pass so the screenshot doesn't include the modal UI.
      */}
      <SheetContent
        id="worldview-feedback-modal-root"
        className="flex w-full max-w-md flex-col overflow-y-auto sm:max-w-lg"
      >
        <SheetHeader>
          <SheetTitle>Send feedback</SheetTitle>
          <SheetDescription>
            Help us improve Worldview — pick a category and tell us what&apos;s on your mind.
          </SheetDescription>
        </SheetHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as TabId)}
          className="mt-3 flex flex-1 flex-col"
        >
          <TabsList className="flex flex-wrap">
            {TABS.map((t) => (
              <TabsTrigger key={t.id} value={t.id}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {/* Each tab renders its own dynamic form — DRY-d below. */}
          {TABS.map((t) => (
            <TabsContent key={t.id} value={t.id} className="mt-4 space-y-3">
              {/* Bug-only severity selector. */}
              {t.id === "bug" && (
                <label className="block">
                  <span className="text-xs text-muted-foreground">Severity</span>
                  <select
                    value={severity}
                    onChange={(e) =>
                      setSeverity(e.target.value as FeedbackSeverity)
                    }
                    className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-[14px] focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="low">Low — minor inconvenience</option>
                    <option value="medium">Medium — some users impacted</option>
                    <option value="high">High — workflow blocked</option>
                    <option value="critical">Critical — production down</option>
                  </select>
                </label>
              )}

              {/* Feature-only title + category. */}
              {t.id === "feature" && (
                <>
                  <label className="block">
                    <span className="text-xs text-muted-foreground">Title</span>
                    <input
                      value={featureTitle}
                      onChange={(e) => setFeatureTitle(e.target.value.slice(0, 200))}
                      maxLength={200}
                      placeholder="One-line summary"
                      className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-[14px] focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-muted-foreground">Category (optional)</span>
                    <input
                      value={featureCategory}
                      onChange={(e) => setFeatureCategory(e.target.value.slice(0, 50))}
                      placeholder="e.g. Portfolio, Charts, Alerts"
                      className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-[14px] focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </label>
                </>
              )}

              {/* Common: description textarea — same field name across all tabs. */}
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  {t.id === "feature" ? "Describe the feature" : "Describe what happened"}
                </span>
                <textarea
                  value={description}
                  onChange={(e) =>
                    setDescription(e.target.value.slice(0, 5000))
                  }
                  rows={5}
                  placeholder={
                    t.id === "bug"
                      ? "Steps to reproduce, expected vs actual…"
                      : t.id === "feature"
                        ? "What problem does it solve? Who would use it?"
                        : "Tell us more…"
                  }
                  className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-[14px] focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <span className="mt-1 block text-right text-[10px] tabular-nums text-muted-foreground">
                  {description.length} / 5000
                </span>
              </label>

              {/* Anonymous email — only visible when the user is not signed in. */}
              {!isAuthenticated && (
                <label className="block">
                  <span className="text-xs text-muted-foreground">Email</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-[14px] focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <span className="mt-1 block text-[10px] text-muted-foreground">
                    Required for anonymous submissions so we can follow up.
                  </span>
                </label>
              )}

              {/* Bug + UX tabs get the optional capture controls. Feature
                  requests don't need a screenshot of a broken state. */}
              {(t.id === "bug" || t.id === "ux") && (
                <>
                  <ScreenshotCapture
                    onCapture={setScreenshotDataUrl}
                    hasCapture={screenshotDataUrl !== null}
                  />
                  <ConsoleLogCapture
                    enabled={includeConsole}
                    onEnabledChange={setIncludeConsole}
                    logs={logs}
                    onClear={clearConsole}
                  />
                </>
              )}

              {/* Contact Us tab gets a small "we'll reply by email" note. */}
              {t.id === "contact" && (
                <p className="rounded-[2px] border border-border bg-card/50 p-2 text-xs text-muted-foreground">
                  We reply within 1 business day on weekdays. For urgent
                  production issues, email support@worldview.app directly.
                </p>
              )}
            </TabsContent>
          ))}
        </Tabs>

        {submitError && (
          <p className="mt-3 text-xs text-destructive" role="alert">
            {submitError}
          </p>
        )}

        <SheetFooter className="mt-auto gap-2 sm:gap-2">
          <SheetClose asChild>
            <Button type="button" variant="ghost" disabled={isSubmitting}>
              Cancel
            </Button>
          </SheetClose>
          <Button type="button" onClick={handleSubmit} disabled={submitDisabled}>
            {isSubmitting && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            Send feedback
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

// ── Internal mutation hook for the feature-request branch ──────────────────
//
// WHY in this file (not a separate hook): only FeedbackModal needs it. The
// public "Suggest a feature" CTA on /feedback opens this same modal with
// defaultTab="feature", so the same mutation handles both surfaces.

function useFeatureSubmit() {
  const { accessToken } = useAuth();
  return useMutation({
    mutationFn: (payload: {
      title: string;
      description: string;
      category: string | null;
    }) =>
      createGateway(accessToken).postFeatureRequest({
        title: payload.title,
        description: payload.description,
        category: payload.category,
      }),
    // WHY retry (CRIT-006 / FR-8.1): postFeatureRequest creates a new proposal;
    // retry on transient 5xx is safe — a duplicate feature request from a retry
    // is preferable to losing the user's input entirely on a network blip.
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onError: (err) => {
      // Surface as plain Error — the formatter handles GatewayError.
      if (err instanceof GatewayError) {
        // The mutation.error field already holds it; nothing else to do.
      }
    },
  });
}
