/**
 * components/ui/backend-pending-badge.tsx — "Backend pending" inline marker
 * (PRD-0089 Wave I-A · Block B · T-IA-06)
 *
 * WHY THIS EXISTS:
 *   Wave I-A ships the FRONTEND for a set of intelligence + fundamentals
 *   filters / columns whose BACKEND has not landed yet (Wave L tracks).
 *   Those rows are rendered today but `disabled`, so users see the roadmap
 *   without being able to interact. A short orange marker next to each
 *   disabled control signals "we know about this; it's on the way" — the
 *   alternative (hiding the rows entirely) would surprise users when the
 *   features eventually appear.
 *
 *   WHY orange (`text-warning`) and not red: red would read as an error.
 *   This isn't an error; it's a "coming soon" affordance. Warning yellow
 *   is the Terminal-Dark token for "needs attention, not broken".
 *
 * VISUAL CONTRACT (locked by the plan, do not adjust without re-spec):
 *   - 9px monospace, ALL-CAPS implied by the default copy.
 *   - `bg-warning/10` tinted background, `text-warning` foreground.
 *   - `px-1.5 py-0` horizontal padding only.
 *   - `rounded-[2px]` — Terminal-Dark forbids any larger radius.
 *   - 14px tall total (matches the 12-14px chip rows it sits next to).
 *
 * WHO USES IT:
 *   - `components/screener/IntelligenceFilterGroup.tsx` (T-IA-07).
 *   - `components/screener/ColumnSettingsPopover.tsx` (T-IA-08).
 *   - Any future "coming soon" affordance across the platform.
 *
 * PLAN REF: docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-06
 */

"use client";
// WHY "use client": cosmetic stateless component, but every consumer lives
// in a client component tree. Mark it client to avoid SSR boundary churn.

export interface BackendPendingBadgeProps {
  /**
   * Optional override for the badge copy. Defaults to "Backend pending".
   * WHY exposed: some surfaces want shorter copy (e.g. "L-3 pending" inside
   * a denser column-settings list). Keeping it open lets each consumer
   * pick the right register without forking the component.
   */
  text?: string;
}

export function BackendPendingBadge({ text = "Backend pending" }: BackendPendingBadgeProps) {
  return (
    // WHY a <span> (not <div>): the badge always sits inline with another
    // element (a label, a row name, a column toggle). A block element would
    // force a line break and ruin the row alignment.
    <span
      role="status"
      aria-label={text}
      className="inline-flex items-center h-[14px] px-1.5 py-0 rounded-[2px] text-[9px] font-mono text-warning bg-warning/10"
    >
      {text}
    </span>
  );
}
