/**
 * components/intelligence/IntelligencePageErrorBoundary.tsx — Per-panel error isolation
 * (PLAN-0074 Wave H T-H-07)
 *
 * WHY PER-PANEL (not page-level) ERROR BOUNDARIES:
 * The intelligence page fetches from 4+ different S9 endpoints in parallel.
 * A single page-level error boundary would kill the entire page if ANY one
 * panel fails (e.g., the KG service is down → graph panel fails → entire page
 * shows error, even though sidebar + chat still work fine). Per-panel isolation
 * means each column degrades independently. Analysts can still use the narrative
 * history and entity chat even when the graph endpoint is down.
 *
 * WHY NOT Sentry.ErrorBoundary HERE:
 * The global Sentry.ErrorBoundary in app/providers.tsx catches catastrophic
 * failures. This component is for graceful per-panel degradation with a retry
 * button — showing a user-friendly message instead of a blank column.
 * Sentry still receives these errors via its global error handler.
 *
 * WHY CLASS COMPONENT (not hooks):
 * React error boundaries MUST be class components. Hooks cannot catch render
 * errors in children — that's a fundamental React constraint. We minimise the
 * class surface by keeping all the logic here and only exposing a clean API.
 *
 * WHO USES IT: app/intelligence/[entity_id]/page.tsx — wraps each of the four panels
 */

"use client";
// WHY "use client": class component with state, cannot be a Server Component.

import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

// ── Props & State ─────────────────────────────────────────────────────────────

interface IntelligencePageErrorBoundaryProps {
  /** Human-readable panel name for the error message ("Graph", "Intelligence", etc.) */
  panelName: string;
  children: ReactNode;
}

interface IntelligencePageErrorBoundaryState {
  hasError: boolean;
  errorMessage: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export class IntelligencePageErrorBoundary extends Component<
  IntelligencePageErrorBoundaryProps,
  IntelligencePageErrorBoundaryState
> {
  constructor(props: IntelligencePageErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  /**
   * getDerivedStateFromError — React lifecycle called when a child throws.
   * Updates state to show the error UI instead of the broken children.
   */
  static getDerivedStateFromError(
    error: Error,
  ): IntelligencePageErrorBoundaryState {
    return {
      hasError: true,
      // WHY truncate: raw error messages can contain internal hostnames or
      // stack traces (e.g. from GatewayError) that should not be shown to users.
      // We show the first 120 chars which usually contains the meaningful part.
      errorMessage: error.message?.slice(0, 120) ?? "Unknown error",
    };
  }

  /**
   * handleRetry — reset the error state so React re-tries rendering the children.
   *
   * WHY this works: error boundaries re-render when their state changes.
   * Resetting hasError=false causes React to try mounting the children again —
   * if the underlying error was transient (network blip), the retry succeeds.
   */
  handleRetry = () => {
    this.setState({ hasError: false, errorMessage: null });
  };

  override render() {
    if (this.state.hasError) {
      return (
        // WHY h-full: the error state should fill the same space as the panel
        // it replaces, so the layout does not shift when one panel fails.
        <div
          className="h-full flex flex-col items-center justify-center gap-3 p-3 text-center"
          role="alert"
          aria-live="polite"
        >
          {/* WHY text-destructive for label: clearly communicates the panel
              failed without being alarming (destructive = red, semantic error color) */}
          <p className="text-destructive text-[11px] font-mono font-medium uppercase tracking-wider">
            {this.props.panelName} panel failed to load
          </p>
          {/* WHY show a truncated error: gives analysts a diagnostic hint
              (e.g. "503 Service Unavailable" vs "authentication required") */}
          {this.state.errorMessage && (
            <p className="text-muted-foreground text-[11px] font-mono max-w-[240px] break-words">
              {this.state.errorMessage}
            </p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={this.handleRetry}
            className="text-[11px] h-7"
            aria-label={`Retry loading the ${this.props.panelName} panel`}
          >
            Retry
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
