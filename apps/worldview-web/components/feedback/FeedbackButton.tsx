/**
 * components/feedback/FeedbackButton.tsx — fixed-position trigger.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-05):
 * Always-visible 56x56px circle bottom-right that opens FeedbackModal.
 * Renders on every shell page regardless of auth status — the user-approved
 * design treats anonymous feedback as first-class (with email required for
 * follow-up). The modal itself surfaces an email input when not authed.
 * We mount it inside (app)/layout.tsx so it follows the shell.
 *
 * KEYBOARD SHORTCUT: cmd+? (or ctrl+?) also opens the modal — power
 * users don't need to mouse over to click. Implemented in this file so
 * the mounted component owns both surfaces; GlobalSearch separately
 * exposes a "Feedback" command in cmd+K (T-G-7-05 spec).
 *
 * EVENT API:
 *   window.dispatchEvent(new CustomEvent("worldview:open-feedback"))
 *     → opens with default tab "bug" and empty description
 *   window.dispatchEvent(new CustomEvent("worldview:open-feedback", {
 *     detail: { tab: "bug" | "feature" | "ux" | "general" | "contact",
 *               description: string }
 *   }))
 *     → opens with the supplied tab + description prefilled.
 *
 * The detail payload powers PLAN-0052 Wave E T-E-5-08 (deep-link bug
 * report from a URL like /any-page?feedback=bug&page=/dashboard).
 *
 * Z-INDEX: z-50 — above page content but below FlashOverlay (z-9999).
 */

"use client";

import { useEffect, useState } from "react";
import { MessageCircle } from "lucide-react";
import { FeedbackModal } from "./FeedbackModal";

/** Discriminated tab id matching FeedbackModal.TabId. Kept narrow on purpose. */
type FeedbackTabId = "bug" | "feature" | "ux" | "general" | "contact";

/** Optional payload that callers can attach to the open-feedback event. */
export interface OpenFeedbackEventDetail {
  /** Which tab to land on. Defaults to "bug". */
  tab?: FeedbackTabId;
  /** Pre-filled textarea content. Capped server-side at 5000 chars. */
  description?: string;
}

/** Type-guard so we don't trust arbitrary detail payloads from untyped events. */
function isOpenFeedbackDetail(value: unknown): value is OpenFeedbackEventDetail {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.tab !== undefined && typeof v.tab !== "string") return false;
  if (v.description !== undefined && typeof v.description !== "string") return false;
  return true;
}

/** Allow-list of valid tab ids — anything else falls back to "bug". */
const VALID_TABS: ReadonlyArray<FeedbackTabId> = [
  "bug",
  "feature",
  "ux",
  "general",
  "contact",
];

/**
 * Compact prefill state. Holds the "next form snapshot" the modal will
 * render when it opens. Manual triggers reset this to EMPTY_PREFILL;
 * deep-link / programmatic triggers replace it from event detail.
 *
 * PLAN-0052 Wave E QA-iter1 arch/M-2: collapsed from two parallel state
 * slots into one shape so the prefill never gets out of sync with itself
 * (e.g. previously: tab updated but description not, or vice-versa).
 */
interface FeedbackPrefill {
  tab: FeedbackTabId;
  description: string;
}

const EMPTY_PREFILL: FeedbackPrefill = { tab: "bug", description: "" };

export function FeedbackButton() {
  // PLAN-0053 QA-iter1 F-010 + iter2 F-003: anonymous feedback is first-class
  // — the modal collects an email when unauthed, so the button renders for
  // every visitor. We removed the previous bare ``useAuth();`` call (a code
  // smell that did nothing) — the modal owns its own auth lookup.
  const [open, setOpen] = useState(false);
  const [prefill, setPrefill] = useState<FeedbackPrefill>(EMPTY_PREFILL);

  // Keyboard shortcut: cmd/ctrl + ? (Shift+/ on most layouts).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // WHY both meta + ctrl: Mac uses meta (cmd), Windows / Linux uses ctrl.
      const isMod = e.metaKey || e.ctrlKey;
      // WHY '?' check (not key === '?'): different layouts emit '?' as
      // shift + '/'. Both `?` and `/` with shiftKey arrive here.
      if (isMod && (e.key === "?" || (e.shiftKey && e.key === "/"))) {
        e.preventDefault();
        // Manual shortcut → reset prefill so the form opens clean.
        setPrefill(EMPTY_PREFILL);
        setOpen(true);
      }
    }
    // Custom-event hook so other surfaces (cmd+K palette command, programmatic
    // triggers in marketing/help flows, deep-link handler) can open the modal
    // without prop-drilling. Detail is optional — see OpenFeedbackEventDetail.
    function onOpenEvent(e: Event) {
      const detail = (e as CustomEvent<unknown>).detail;
      if (isOpenFeedbackDetail(detail)) {
        // Validate the tab against the allow-list before trusting it; an
        // unknown value falls back to "bug" so we don't crash in
        // FeedbackModal's TABS.find().
        const tab =
          detail.tab && (VALID_TABS as readonly string[]).includes(detail.tab)
            ? detail.tab
            : "bug";
        setPrefill({
          tab,
          // Cap to 5000 chars (backend max) so the modal's slice() doesn't
          // need to also re-cap the prefill.
          description: (detail.description ?? "").slice(0, 5000),
        });
      } else {
        // Bare dispatch — reset to a clean form.
        setPrefill(EMPTY_PREFILL);
      }
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("worldview:open-feedback", onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("worldview:open-feedback", onOpenEvent);
    };
  }, []);

  // When the user closes the modal, drop the prefill so the next manual
  // click opens an empty form.
  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setPrefill(EMPTY_PREFILL);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          // Manual click → reset prefill so the form opens clean.
          setPrefill(EMPTY_PREFILL);
          setOpen(true);
        }}
        // PLAN-0052 Wave E QA-iter1 a11y/M-1: keep the primary aria-label
        // clean ("Send feedback") so screen readers announce the action,
        // and expose the keyboard shortcut via the standard aria-keyshortcuts
        // attribute. Embedding the shortcut inside aria-label produced a
        // verbose audio mouthful ("send feedback open paren cmd slash ctrl
        // plus shift plus slash close paren") on NVDA + VoiceOver. The
        // visible `title` retains the shortcut hint for sighted users.
        aria-label="Send feedback"
        aria-keyshortcuts="Meta+Shift+Slash Control+Shift+Slash"
        title="Send feedback (Cmd/Ctrl+Shift+/)"
        className={[
          // Position: fixed bottom-right with breathing room from edges.
          "fixed bottom-6 right-6 z-50",
          // Size: 56px circle per spec.
          "h-14 w-14 rounded-full",
          // Look: primary action surface — same as Bloomberg-style accent.
          "bg-primary text-primary-foreground",
          "shadow-lg shadow-primary/20",
          // Interaction states.
          "hover:bg-primary/90 active:bg-primary/80",
          // Focus ring for keyboard nav.
          "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background",
          // PLAN-0052 Wave E QA-iter1 a11y/M-3: motion-safe so users with
          // prefers-reduced-motion don't get the press-scale animation.
          "motion-safe:transition-transform motion-safe:active:scale-95",
          // Center the icon glyph.
          "flex items-center justify-center",
        ].join(" ")}
      >
        <MessageCircle className="h-6 w-6" aria-hidden="true" />
      </button>

      <FeedbackModal
        open={open}
        onOpenChange={handleOpenChange}
        defaultTab={prefill.tab}
        defaultDescription={prefill.description}
      />
    </>
  );
}
