/**
 * components/data/InlineErrorState.tsx — Compact inline error state for data panels
 *
 * WHY THIS EXISTS: Terminal panels must degrade professionally when data fails to
 * load. A full-height centered error card breaks the panel layout and looks
 * consumer-grade. This component shows a single compact error line that preserves
 * the panel structure while clearly signaling the failure.
 *
 * WHY text-destructive (not error icon): text color alone distinguishes the error
 * state from the normal empty state without adding visual weight (no large icon,
 * no card, no border). The destructive token maps to --destructive-foreground in
 * the Terminal Dark palette.
 *
 * WHO USES IT: AlertsList, FundamentalsTab, IntelligenceTab, any data panel
 *             that shows an error without a full-page recovery path.
 * DESIGN REFERENCE: PRD-0028 §6.5 Terminal Design Rules §4.5
 */

// WHY no "use client": pure presentational, no hooks or browser APIs.

import { cn } from "@/lib/utils";

interface InlineErrorStateProps {
  /** The error message to display. Defaults to "Failed to load data." */
  message?: string;
  /** Optional extra Tailwind classes */
  className?: string;
}

/**
 * InlineErrorState — a single compact error line for data panels.
 *
 * Usage:
 *   <InlineErrorState />
 *   <InlineErrorState message="Failed to load alerts." />
 */
export function InlineErrorState({
  message = "Failed to load data.",
  className,
}: InlineErrorStateProps) {
  return (
    // WHY text-destructive text-xs py-3: matches InlineEmptyState footprint.
    // Uses destructive color (red in Terminal Dark) to clearly signal failure
    // without needing a separate error icon or card border.
    <p className={cn("py-3 text-xs text-destructive", className)}>
      {message}
    </p>
  );
}
