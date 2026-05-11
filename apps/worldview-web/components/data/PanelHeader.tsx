/**
 * components/data/PanelHeader.tsx — Compact terminal panel header strip
 *
 * WHY THIS EXISTS: Every terminal panel needs a consistent header: a 28-32px strip
 * with a title (ALL CAPS, small, muted) and an optional action slot (button, badge).
 * Without a shared primitive, every panel reimplements this with slightly different
 * padding, font sizes, or border styles — creating inconsistency across the app.
 *
 * WHY h-6 (24px): Terminal panel headers are 24px tall per §0.2 of the Terminal CLI
 * Quality Standard. Taller headers (h-8, h-10) waste vertical space in dense
 * multi-panel layouts. h-6 is the compact terminal standard.
 *
 * WHY border-b border-border/40: the header divider uses 40% opacity to create a
 * visual separation without a harsh full-opacity line. Matches the card/panel
 * border style used throughout the design system.
 *
 * WHY text-[10px] uppercase tracking-wider: Bloomberg terminal column headers
 * and panel labels use this exact style — small caps with wide tracking reads
 * as "category label" rather than "content", reducing cognitive noise.
 *
 * WHO USES IT: Any data panel component needing a consistent header strip.
 * DESIGN REFERENCE: PRD-0028 §6.5 Terminal Design Rules §4.2
 */

// WHY no "use client": pure presentational, no hooks or browser APIs.

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface PanelHeaderProps {
  /** Panel title — rendered as ALL CAPS small text */
  title: string;
  /**
   * Optional action slot (e.g. a Button, Badge, or dropdown trigger).
   * Rendered right-aligned in the header strip.
   */
  action?: ReactNode;
  /** Optional extra Tailwind classes */
  className?: string;
}

/**
 * PanelHeader — compact terminal panel header with title + optional action.
 *
 * Usage:
 *   <PanelHeader title="Holdings" />
 *   <PanelHeader title="Top Movers" action={<RefreshButton />} />
 */
export function PanelHeader({ title, action, className }: PanelHeaderProps) {
  return (
    // WHY h-6 items-center: 24px height with vertical centering per §0.2 Terminal CLI
    // Quality Standard. border-b divides the header from the content.
    <div
      className={cn(
        "flex h-6 items-center justify-between border-b border-border/40 px-3",
        className,
      )}
    >
      {/* Title: small, uppercase, wide tracking — terminal label aesthetic */}
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </span>

      {/* Action slot: right-aligned; only rendered when provided */}
      {action != null && (
        <div className="flex items-center gap-1">
          {action}
        </div>
      )}
    </div>
  );
}
