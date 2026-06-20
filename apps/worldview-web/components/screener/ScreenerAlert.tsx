/**
 * components/screener/ScreenerAlert.tsx — designed inline error/warning callout
 * for the screener surface (UI competitive-roadmap item #6b / A3).
 *
 * WHY THIS EXISTS:
 *   The NL screen builder previously surfaced backend failures as a bare line of
 *   red text (`<p class="text-negative">`). The roadmap audit flags that as a
 *   "looks like a bug" tell — a raw error string reads as an unhandled crash,
 *   not a designed state. A proper Alert (bordered surface + leading icon +
 *   readable copy) signals "we anticipated this and handled it."
 *
 * WHY A LOCAL COMPONENT (not components/ui/alert):
 *   There is no shadcn `Alert` in components/ui (only `alert-dialog`), and this
 *   work is scoped to the screener surface only — we may not add to
 *   components/ui. components/data/InlineErrorState exists but is itself just
 *   red text with no border/icon, i.e. the very pattern the audit asks us to
 *   upgrade. So we build a small, self-contained, terminal-grade callout here.
 *
 * DESIGN (docs/ui/DESIGN_SYSTEM.md — Terminal Dark):
 *   - 2px-radius bordered surface tinted by variant (destructive red / amber
 *     warning), at low alpha so it sits quietly inside the dense toolbar.
 *   - Leading lucide icon for instant variant recognition (AlertTriangle), at
 *     the 1.5 stroke weight used across the app's icons.
 *   - `font-mono` body copy matching the surrounding NL search input.
 *   - role="alert" for errors / role="status" for warnings so assistive tech
 *     announces failures but not soft hints.
 */

"use client";

import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ScreenerAlertProps {
  /**
   * Visual + semantic severity.
   *   "error"   → red destructive tint, role="alert" (a request failed)
   *   "warning" → amber tint, role="status" (a soft, non-failing hint)
   */
  variant?: "error" | "warning";
  /** The message body. Plain text or rich nodes (e.g. an inline error detail). */
  children: React.ReactNode;
  /** Optional extra Tailwind classes for layout tweaks at the call site. */
  className?: string;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * ScreenerAlert — compact, bordered, icon-led callout.
 *
 * Usage:
 *   <ScreenerAlert variant="error">Couldn't translate that screen — {msg}</ScreenerAlert>
 *   <ScreenerAlert variant="warning">Try naming a metric (P/E, market cap…).</ScreenerAlert>
 */
export function ScreenerAlert({
  variant = "error",
  children,
  className,
}: ScreenerAlertProps) {
  const isError = variant === "error";
  return (
    <div
      // role distinguishes a hard failure (assertive "alert") from a soft hint
      // (polite "status") for screen readers — matches the prior NlScreenerSearch
      // a11y contract that the bare <p> tags carried.
      role={isError ? "alert" : "status"}
      className={cn(
        // Bordered, low-alpha tinted surface at the app's 2px terminal radius.
        "flex items-start gap-1.5 rounded-[2px] border px-2 py-1.5",
        isError
          ? "border-negative/40 bg-negative/10 text-negative"
          : "border-warning/40 bg-warning/10 text-warning",
        className,
      )}
    >
      <AlertTriangle
        className="mt-px h-3.5 w-3.5 shrink-0"
        aria-hidden
        strokeWidth={1.5}
      />
      {/* font-mono + 10px keeps the copy consistent with the NL search input
          row this Alert sits beneath. leading-snug avoids a tall block when the
          backend error message wraps to two lines. */}
      <span className="text-[10px] font-mono leading-snug">{children}</span>
    </div>
  );
}
