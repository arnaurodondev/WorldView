/**
 * components/ui/dashboard-empty-state.tsx — Centred empty-state block
 *
 * WHY THIS EXISTS: Several dashboard widgets show an empty state when there
 * is genuinely no data (no holdings, no alerts, no watchlists). Each one had
 * its own bespoke layout; this shared component standardises the pattern:
 *   - centred flex column
 *   - small heading (terminal voice — UPPERCASE, tracked, primary text)
 *   - muted secondary line
 *   - optional CTA link
 *
 * WHEN TO USE:
 *   - Use this for dashboard / page-level empty states (full panel area).
 *   - Use <InlineEmptyState> (../data/InlineEmptyState.tsx) for empty rows
 *     inside an existing table or list — that variant is a single muted line.
 */

// WHY no "use client": pure presentational, no state or browser APIs.

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface DashboardEmptyStateProps {
  /** Heading line (e.g. "No alerts yet"). */
  title: string;
  /** Body / explanation line — slightly muted. */
  message: string;
  /** Optional call-to-action link. */
  cta?: { label: string; href: string };
  /** Optional extra Tailwind classes for the wrapper. */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function DashboardEmptyState({
  title,
  message,
  cta,
  className,
}: DashboardEmptyStateProps): ReactNode {
  return (
    // WHY py-8: enough room to feel like a deliberate empty state without
    // ballooning the panel height (which would shift the whole dashboard).
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-1 py-8 text-center",
        className,
      )}
      role="status"
    >
      {/* Title — terminal-style: UPPERCASE, tracked, primary-toned. */}
      <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-foreground">
        {title}
      </p>
      {/* Message — muted secondary line. text-xs ≈ 12px feels right under
          the 11px uppercase title (not so close they merge, not so far they
          look unrelated). */}
      <p className="text-xs text-muted-foreground">{message}</p>
      {cta && (
        // CTA — primary-coloured link. Uses Next Link so prefetch + client
        // navigation works for in-app routes; if the href is external the
        // caller can wrap their own <a>.
        <Link
          href={cta.href}
          className="mt-1 font-mono text-[10px] uppercase tracking-[0.06em] text-primary hover:underline"
        >
          {cta.label}
        </Link>
      )}
    </div>
  );
}
