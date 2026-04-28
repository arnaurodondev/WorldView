/**
 * components/instrument/EntityGraphErrorBoundary.tsx — class error boundary
 * around the dynamic-imported sigma.js EntityGraph.
 *
 * WHY THIS EXISTS (PLAN-0050 T-F-6-19, closes F-I-033): the EntityGraph is
 * a heavy WebGL component (sigma.js + graphology) loaded lazily via
 * `next/dynamic`. Two failure modes that have shown up in audits:
 *
 *   1. WebGL context creation fails (older browser, GPU disabled, or the
 *      headless browser the QA agent uses). Throws synchronously inside
 *      sigma's constructor.
 *   2. Malformed graph data (a missing node referenced by an edge) makes
 *      graphology throw `UsageGraphError`.
 *
 * Without a boundary, those errors propagate up the React tree and tear
 * down the *entire* Intelligence tab — the trader sees a blank page where
 * the brief, contradictions, and graph all used to be. A boundary scoped
 * tightly around the graph keeps the rest of the tab alive and shows a
 * graceful fallback that explains what failed.
 *
 * WHY a CLASS component: error boundaries are still class-only in React 18
 * (componentDidCatch / getDerivedStateFromError). React 19 may add a hook
 * but until then class is the supported path.
 *
 * WHY render the Intelligence tab's surrounding chrome unaffected: the
 * boundary only wraps the EntityGraph subtree — its parent section
 * (header + entity count) renders normally even if the graph crashes.
 */

"use client";
// WHY "use client": class components with state must execute in the browser.

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string | null;
}

export class EntityGraphErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // WHY console.error (not a Sentry/structured logger here): the frontend
    // does not yet wire a client telemetry sink (ADR-F-XX deferred). When
    // it does, this is the single place to forward graph crashes.
    // eslint-disable-next-line no-console
    console.error("[EntityGraph] crashed:", error, info.componentStack);
  }

  reset = () => this.setState({ hasError: false, message: null });

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex h-[460px] flex-col items-center justify-center gap-2 rounded-[2px] border border-warning/40 bg-warning/5 p-4 text-center"
        >
          <AlertTriangle className="h-5 w-5 text-warning" aria-hidden="true" />
          <p className="text-xs text-foreground">Could not render the entity graph.</p>
          <p className="max-w-xs text-[10px] text-muted-foreground">
            {this.state.message ?? "Unknown error in graph layout."}
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="mt-1 rounded-[2px] border border-border bg-muted px-2 py-1 text-[10px] text-foreground hover:bg-muted/70"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
