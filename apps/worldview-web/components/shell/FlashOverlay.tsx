/**
 * components/shell/FlashOverlay.tsx — Full-screen critical alert overlay
 *
 * WHY THIS EXISTS: CRITICAL severity alerts (e.g., circuit breaker triggered,
 * margin call, major company event) must be impossible to miss. A full-viewport
 * overlay with a countdown timer ensures the trader sees it before it auto-dismisses.
 *
 * WHY AUTO-DISMISS (not require manual close):
 * Traders can't afford to have their workflow blocked by a stuck overlay.
 * 12 seconds is enough to read the alert and decide whether to act on it.
 * The countdown bar shows exactly how much time remains.
 *
 * WHY ERROR BOUNDARY: A malformed alert payload (e.g., null message) could
 * crash the render. Since this overlay sits outside the main content tree,
 * a crash here would take down the entire app. The ErrorBoundary limits blast radius.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered in the layout so it covers all pages
 * DATA SOURCE: AlertStreamContext.criticalQueue
 * DESIGN REFERENCE: PRD-0028 §6.5 FlashOverlay, PRD-0021 §3 FR-15
 */

"use client";
// WHY "use client": Uses useEffect (keyboard event listener, countdown timer),
// useState (countdown value), and DOM event handling.

import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, X } from "lucide-react";
import { useAlertStream } from "@/contexts/AlertStreamContext";

import type { AlertPayload } from "@/types/alerts";

// ── Auto-dismiss duration ─────────────────────────────────────────────────────

/** Overlay auto-dismisses after 12 seconds — enough to read and assess */
const AUTO_DISMISS_MS = 12_000;

// ── Error Boundary ────────────────────────────────────────────────────────────

/**
 * AlertErrorBoundary — catches render errors in the overlay content
 *
 * WHY class component: React Error Boundaries can only be class components
 * (as of React 18 — hooks cannot replicate componentDidCatch / getDerivedStateFromError).
 */
interface ErrorBoundaryState {
  hasError: boolean;
}

class AlertErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  override componentDidCatch(error: Error): void {
    // In production, this would go to an error tracking service (Sentry/Glitchtip)
    // For now, log to console so the dev can see the malformed alert
    console.error("[FlashOverlay] Render error — possibly malformed alert payload:", error);
  }

  override render() {
    if (this.state.hasError) {
      // WHY still show something: better to show a degraded overlay than nothing.
      // The user still needs to know a critical alert fired.
      return (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90">
          <div className="text-center text-foreground">
            <AlertTriangle className="mx-auto h-8 w-8 text-destructive" />
            <p className="mt-2 text-sm">Critical alert (display error)</p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Overlay content ───────────────────────────────────────────────────────────

interface FlashOverlayContentProps {
  alert: AlertPayload;
  onDismiss: () => void;
}

function FlashOverlayContent({ alert, onDismiss }: FlashOverlayContentProps) {
  // Countdown from AUTO_DISMISS_MS ms to 0
  const [remainingMs, setRemainingMs] = useState(AUTO_DISMISS_MS);
  const startTimeRef = useRef(Date.now());

  // Auto-dismiss timer + countdown
  useEffect(() => {
    const intervalId = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const remaining = AUTO_DISMISS_MS - elapsed;
      if (remaining <= 0) {
        onDismiss();
      } else {
        setRemainingMs(remaining);
      }
    }, 100); // WHY 100ms: smooth progress bar without excessive re-renders

    // Cleanup: clear interval when alert changes or overlay unmounts
    return () => clearInterval(intervalId);
  }, [onDismiss]); // onDismiss is stable (useCallback in parent)

  // Keyboard dismiss: Escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onDismiss();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onDismiss]);

  // Progress bar width: 100% → 0% over 12 seconds
  const progressPct = (remainingMs / AUTO_DISMISS_MS) * 100;
  const remainingSec = Math.ceil(remainingMs / 1000);

  // BT-006 FIX: severityColor() returns CSS class names (e.g., "text-negative"),
  // NOT human-readable labels. Use alert.severity directly for the label text.

  return (
    // WHY inset-0 z-[9999]: must cover everything including modals and dropdowns.
    // WHY bg-black/80: semi-transparent to show user their dashboard is still there.
    // WHY onClick on overlay (not just X button): Bloomberg-style — click anywhere to dismiss.
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80"
      onClick={onDismiss}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="flash-alert-title"
      aria-describedby="flash-alert-message"
    >
      <div
        className="relative w-full max-w-lg overflow-hidden rounded-[2px] border border-destructive/50 bg-background"
        onClick={(e) => e.stopPropagation()} // WHY stopPropagation: prevent backdrop click from bubbling
      >
        {/* Countdown progress bar — red fills from left, shrinks right to left */}
        <div
          className="absolute left-0 top-0 h-1 bg-destructive transition-none"
          style={{ width: `${progressPct}%` }}
        />

        <div className="p-4">
          {/* Header: severity badge + close button */}
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              <span id="flash-alert-title" className="text-sm font-semibold uppercase tracking-wider text-destructive">
                {alert.severity} Alert
              </span>
            </div>

            <button
              onClick={onDismiss}
              className="text-muted-foreground hover:text-foreground"
              aria-label={`Dismiss in ${remainingSec}s`}
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Alert message */}
          <p id="flash-alert-message" className="mt-3 text-base font-medium text-foreground">
            {alert.message}
          </p>

          {/* Metadata */}
          <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
            {alert.alert_type && (
              <span>{alert.alert_type.replace(/_/g, " ")}</span>
            )}
            {alert.entity_id && (
              <span className="font-mono">{alert.entity_id}</span>
            )}
            {/* WHY optional guard: a malformed WebSocket payload could arrive with
                created_at=undefined — this guard prevents RangeError from crashing the overlay */}
            <span className="ml-auto font-mono">
              {alert.created_at ? new Date(alert.created_at).toISOString().slice(11, 19) + " UTC" : "—"}
            </span>
          </div>

          {/* Dismiss hint */}
          <p className="mt-4 text-center text-xs text-muted-foreground">
            Auto-dismissing in {remainingSec}s — click anywhere or press Esc to dismiss now
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function FlashOverlay() {
  const { criticalQueue, dequeueCritical } = useAlertStream();

  // WHY useCallback: ensures stable reference for useEffect deps in FlashOverlayContent
  const handleDismiss = useCallback(() => {
    dequeueCritical();
  }, [dequeueCritical]);

  // Show the first item in the queue (oldest critical alert)
  const currentAlert = criticalQueue[0];

  if (!currentAlert) return null; // WHY: nothing to show

  return (
    <AlertErrorBoundary>
      <FlashOverlayContent alert={currentAlert} onDismiss={handleDismiss} />
    </AlertErrorBoundary>
  );
}
