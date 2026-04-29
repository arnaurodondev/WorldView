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

import { useEffect, useMemo, useState } from "react";
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
}

export function FeedbackModal({ open, onOpenChange, defaultTab = "bug" }: FeedbackModalProps) {
  const { user, isAuthenticated } = useAuth();
  const submitFeedback = useFeedbackSubmit();
  // WHY a separate mutation here: the "feature" tab posts to a different
  // endpoint (POST /v1/feedback/features), not /submissions. Keeping it
  // local avoids polluting useFeedbackSubmit with branch logic.
  const submitFeature = useFeatureSubmit();

  // ── Form state ──────────────────────────────────────────────────────────
  const [tab, setTab] = useState<TabId>(defaultTab);
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<FeedbackSeverity>("medium");
  const [email, setEmail] = useState("");
  const [featureTitle, setFeatureTitle] = useState("");
  const [featureCategory, setFeatureCategory] = useState("");

  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [includeConsole, setIncludeConsole] = useState(false);
  const { logs, clear: clearConsole } = useConsoleCapture(includeConsole);

  // Reset form when the modal closes — avoids stale state on next open.
  useEffect(() => {
    if (!open) {
      setDescription("");
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
    }
    // We intentionally exclude submit* and clearConsole from deps to avoid
    // re-running this on every render — they're stable references.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultTab]);

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
        // We pack metadata + console logs (when opted-in) + screenshot
        // marker into the JSON `console_logs` column. The backend treats
        // it as opaque JSON. screenshot_url stays null until the upload
        // pipeline lands — see ScreenshotCapture.tsx comment.
        console_logs: {
          metadata: meta,
          console: includeConsole ? logs : null,
          screenshot_data_uri_present: screenshotDataUrl !== null,
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
            Help us improve Worldview — pick a category and tell us what's on your mind.
          </SheetDescription>
        </SheetHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as TabId)}
          className="mt-3 flex flex-1 flex-col"
        >
          <TabsList className="flex flex-wrap">
            {TABS.map((t) => (
              <TabsTrigger key={t.id} value={t.id} className="text-xs">
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
                    className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
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
                      className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs text-muted-foreground">Category (optional)</span>
                    <input
                      value={featureCategory}
                      onChange={(e) => setFeatureCategory(e.target.value.slice(0, 50))}
                      placeholder="e.g. Portfolio, Charts, Alerts"
                      className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
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
                  className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
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
                    className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
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
    onError: (err) => {
      // Surface as plain Error — the formatter handles GatewayError.
      if (err instanceof GatewayError) {
        // The mutation.error field already holds it; nothing else to do.
      }
    },
  });
}
