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
 * Z-INDEX: z-50 — above page content but below FlashOverlay (z-9999).
 */

"use client";

import { useEffect, useState } from "react";
import { MessageCircle } from "lucide-react";
import { FeedbackModal } from "./FeedbackModal";

export function FeedbackButton() {
  // PLAN-0053 QA-iter1 F-010 + iter2 F-003: anonymous feedback is first-class
  // — the modal collects an email when unauthed, so the button renders for
  // every visitor. We removed the previous bare ``useAuth();`` call (a code
  // smell that did nothing) — the modal owns its own auth lookup.
  const [open, setOpen] = useState(false);

  // Keyboard shortcut: cmd/ctrl + ? (Shift+/ on most layouts).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // WHY both meta + ctrl: Mac uses meta (cmd), Windows / Linux uses ctrl.
      const isMod = e.metaKey || e.ctrlKey;
      // WHY '?' check (not key === '?'): different layouts emit '?' as
      // shift + '/'. Both `?` and `/` with shiftKey arrive here.
      if (isMod && (e.key === "?" || (e.shiftKey && e.key === "/"))) {
        e.preventDefault();
        setOpen(true);
      }
    }
    // Custom-event hook so other surfaces (cmd+K palette command, programmatic
    // triggers in marketing/help flows) can open the modal without prop-drilling.
    function onOpenEvent() {
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("worldview:open-feedback", onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("worldview:open-feedback", onOpenEvent);
    };
  }, []);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Send feedback (Ctrl+Shift+/)"
        title="Send feedback"
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
          // Animations: small scale on press for tactile feel.
          "transition-transform active:scale-95",
          // Center the icon glyph.
          "flex items-center justify-center",
        ].join(" ")}
      >
        <MessageCircle className="h-6 w-6" aria-hidden="true" />
      </button>

      <FeedbackModal open={open} onOpenChange={setOpen} />
    </>
  );
}
