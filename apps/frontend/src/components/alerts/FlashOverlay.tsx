import { Component, type ReactNode, useEffect } from "react";
import type { AlertPayload } from "../../hooks/useAlertStream";
import { SeverityBadge } from "./SeverityBadge";

// ── Error Boundary ────────────────────────────────────────────────────────────

interface ErrorBoundaryProps {
  onError: () => void;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

/**
 * Class-based error boundary wrapping FlashOverlay.
 * On any render error: logs to console, calls onError (dequeues the alert),
 * and renders nothing — preventing a broken overlay from crashing the page.
 */
class FlashOverlayErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error): void {
    console.error("[FlashOverlay] render error — dismissing overlay:", error);
    this.props.onError();
  }

  render(): ReactNode {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}

// ── Inner Component ───────────────────────────────────────────────────────────

interface FlashOverlayProps {
  alert: AlertPayload;
  onDismiss: () => void;
}

function FlashOverlayInner({ alert, onDismiss }: FlashOverlayProps) {
  // Auto-dismiss after 12 seconds (PRD §6.6)
  useEffect(() => {
    const timer = setTimeout(onDismiss, 12_000);
    return () => clearTimeout(timer);
  }, [alert.alert_id, onDismiss]);

  // Keyboard: Escape dismisses
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onDismiss]);

  return (
    // Fixed overlay: z-9999, semi-transparent dark background
    // Click on background (not card) → dismiss
    <div
      data-testid="flash-overlay"
      onClick={onDismiss}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(0,0,0,0.75)",
        backdropFilter: "blur(4px)",
      }}
    >
      {/* Card: click does NOT propagate to overlay (stopPropagation) */}
      <div
        data-testid="flash-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "var(--bg-secondary)",
          border: "1px solid var(--border)",
          borderRadius: "0.5rem",
          padding: "1.5rem",
          maxWidth: "600px",
          width: "calc(100% - 2rem)",
          boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
        }}
      >
        <h2
          style={{
            color: "#dc2626",
            fontSize: "1.25rem",
            fontWeight: 700,
            marginBottom: "0.5rem",
          }}
        >
          ⚡ CRITICAL ALERT
        </h2>
        <p style={{ fontWeight: 500, marginBottom: "0.25rem" }}>
          {alert.alert_type}
        </p>
        <p
          style={{
            color: "var(--text-secondary)",
            fontSize: "0.875rem",
            fontFamily: "monospace",
            marginBottom: "1rem",
          }}
        >
          {alert.entity_id}
        </p>
        <SeverityBadge severity="critical" />
        {/* Countdown progress bar: CSS animation from 100%→0% over 12s */}
        <div
          style={{
            marginTop: "1rem",
            height: "4px",
            backgroundColor: "var(--border)",
            borderRadius: "2px",
            overflow: "hidden",
          }}
        >
          <div
            data-testid="countdown-bar"
            style={{
              height: "100%",
              backgroundColor: "#dc2626",
              animation: "flash-countdown 12s linear forwards",
            }}
          />
        </div>
        <p
          style={{
            fontSize: "0.75rem",
            color: "var(--text-secondary)",
            marginTop: "0.25rem",
          }}
        >
          Auto-dismisses in 12 seconds — press Escape to close
        </p>
      </div>
    </div>
  );
}

// ── Public Export ─────────────────────────────────────────────────────────────

/**
 * Full-viewport critical alert overlay.
 * Wrapped in an ErrorBoundary: any render error silently dequeues the alert
 * rather than crashing the page.
 */
export function FlashOverlay(props: FlashOverlayProps) {
  return (
    <FlashOverlayErrorBoundary onError={props.onDismiss}>
      <FlashOverlayInner {...props} />
    </FlashOverlayErrorBoundary>
  );
}
