/**
 * components/instrument/shared/EmptyState.tsx — named empty state (icon + headline)
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 4): every section of the
 * instrument page must render either real data or an EXPLICIT named state —
 * a bare italic sentence (the previous pattern) is easy to mistake for a
 * rendering failure. This component standardises the terminal-style pattern:
 *   - lucide icon (muted, 16px) — instant visual category
 *   - UPPERCASE mono headline — "this is a deliberate state, not a bug"
 *   - optional hint line — what would make data appear here
 *
 * WHY NOT the existing alternatives:
 *  - components/primitives/EmptyState.tsx (PRD-0089 F1 §3.2): condition +
 *    copyKey pattern resolving through lib/copy/empty-states.ts — but it is
 *    ICON-LESS, and adding icon support + new copy keys means touching
 *    lib/copy/ and primitives/, which belong to the design-system surface
 *    (outside this surface's ownership). Flagged in the Round-1 report for
 *    consolidation: ideally that primitive grows an `icon` prop and this
 *    component becomes a thin wrapper over it.
 *  - components/ui/dashboard-empty-state.tsx: also icon-less, tuned for
 *    full-panel dashboard widgets with CTA links.
 *
 * WHO USES IT: NewsColumn, GraphColumn, ContextPanel, ContradictionsBlock.
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  /** Lucide icon component (e.g. Newspaper, Share2) — rendered muted at 16px. */
  readonly icon: LucideIcon;
  /** Short UPPERCASE-styled headline, e.g. "No articles yet". */
  readonly headline: string;
  /** Optional muted explanation of what fills this section. */
  readonly hint?: string;
  /**
   * Layout density:
   *  - "block"  — centred, py-8, for full column/panel areas (news rail, graph).
   *  - "inline" — left-aligned, py-2, for sub-sections inside a stacked rail
   *               (contradictions block) where a centred block would look lost.
   */
  readonly variant?: "block" | "inline";
  /** Optional extra Tailwind classes for the wrapper. */
  readonly className?: string;
}

export function EmptyState({
  icon: Icon,
  headline,
  hint,
  variant = "block",
  className,
}: EmptyStateProps) {
  return (
    // WHY role="status": announces the state to screen readers — an empty
    // section IS information ("there are no contradictions"), not absence.
    <div
      role="status"
      data-testid="empty-state"
      className={cn(
        variant === "block"
          ? "flex flex-col items-center justify-center gap-1.5 px-4 py-8 text-center"
          : "flex flex-col items-start gap-1 px-0 py-2 text-left",
        className,
      )}
    >
      {/* WHY items-center row for inline variant: icon and headline sit on
          one line at inline density; the block variant stacks them. */}
      <div className={cn("flex items-center gap-1.5", variant === "block" && "flex-col gap-1.5")}>
        {/* strokeWidth 1.5 matches the loading spinners elsewhere on the tab. */}
        <Icon className="size-4 text-muted-foreground/60" strokeWidth={1.5} aria-hidden />
        {/* Terminal voice: 10px UPPERCASE tracked mono — same register as the
            section labels it sits under, so it reads as a state of the
            section rather than new content. */}
        <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {headline}
        </p>
      </div>
      {hint && (
        <p className="text-[10px] leading-[1.5] text-muted-foreground/60">{hint}</p>
      )}
    </div>
  );
}
