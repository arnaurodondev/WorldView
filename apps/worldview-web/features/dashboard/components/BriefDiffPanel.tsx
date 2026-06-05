/**
 * features/dashboard/components/BriefDiffPanel.tsx — Expandable diff view
 * showing new and removed bullets since yesterday's brief (PLAN-0066 Wave F T-W10-F-01).
 *
 * WHY THIS EXISTS: When the BriefDiffBadge is clicked, this panel slides in below
 * it to show exactly which bullet points are new (green +) and which were removed
 * (muted strikethrough). The trader can immediately identify what changed without
 * reading the full brief in detail.
 *
 * DESIGN PRINCIPLES:
 * - New bullets: green text with a "+" prefix (standard diff convention).
 * - Removed bullets: muted text with line-through (gray, visually receding).
 * - Delta summary at the top: a one-liner like "3 new, 1 removed since 2026-05-07".
 * - Panel is overlaid (absolute/relative) so it doesn't affect card layout height.
 *
 * WHO USES IT: BriefDiffBadge (rendered inline when expanded).
 * DATA SOURCE: BriefDiffResponse passed down from BriefDiffBadge.
 */

"use client";
// WHY "use client": uses onClick handlers (interactive close button).

import type { BriefDiffResponse, BriefDiffBullet } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BriefDiffPanelProps {
  diff: BriefDiffResponse;
  onClose: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BriefDiffPanel({ diff, onClose }: BriefDiffPanelProps) {
  const hasNew = diff.new_bullets.length > 0;
  const hasRemoved = diff.removed_bullets.length > 0;

  return (
    // WHY z-10: panel must sit above adjacent card content. mt-1 creates visual
    // separation between the badge button and the panel content.
    // WHY w-72: wide enough to read bullet text without being as wide as the card.
    <div
      // WHY rounded-[2px] (was rounded-md=6px): the Terminal Dark scale
      // collapses all corner radii to 2px for the institutional sharp look.
      // 6px reads as a consumer-app pattern.
      // WHY max-h-[60vh] overflow-y-auto: when the diff has many bullets (6+ new + removed),
      // the unconstrained panel extends off-screen. Capping at 60vh with scroll keeps it
      // fully readable without pushing it past the viewport boundary.
      className="z-10 mt-1 w-72 max-h-[60vh] overflow-y-auto rounded-[2px] border border-border bg-card p-3 text-[11px] shadow-md"
      data-testid="brief-diff-panel"
    >
      {/* ── Delta summary ───────────────────────────────────────────────── */}
      <div className="mb-2 flex items-start justify-between gap-2">
        {/* WHY text-muted-foreground: delta_summary is contextual metadata, not
            primary content. Muted keeps visual hierarchy clear. */}
        <span className="text-muted-foreground leading-snug">{diff.delta_summary}</span>
        <button
          onClick={onClose}
          aria-label="Close diff panel"
          // WHY ml-auto shrink-0: close button pins to the top-right without wrapping
          // when the summary text is long.
          className="ml-auto shrink-0 text-muted-foreground hover:text-foreground transition-colors"
        >
          x
        </button>
      </div>

      {/* ── New bullets ─────────────────────────────────────────────────── */}
      {hasNew && (
        <div className="mb-2">
          {/* WHY text-positive (was off-palette text-green-400): --positive
              is the Terminal Dark institutional green; mirroring price-up
              colour keeps "new" semantics consistent. */}
          <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-positive/70">
            New
          </p>
          <ul className="m-0 list-none space-y-0.5 p-0">
            {diff.new_bullets.map((bullet: BriefDiffBullet, i: number) => (
              <li
                key={`new-${i}`}
                // WHY text-positive (was text-green-400): standard diff convention —
                // green = addition; the design token resolves to the institutional
                // green (#00D26A) and matches Bloomberg event feed colour language.
                className="flex gap-1 leading-snug text-positive"
              >
                {/* WHY "+" prefix: explicit diff marker makes the semantic clear
                    even without colour (accessible for colour-blind users). */}
                <span className="shrink-0 font-mono">+</span>
                <span className="text-foreground/90">{bullet.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Removed bullets ─────────────────────────────────────────────── */}
      {hasRemoved && (
        <div>
          <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/60">
            Removed
          </p>
          <ul className="m-0 list-none space-y-0.5 p-0">
            {diff.removed_bullets.map((bullet: BriefDiffBullet, i: number) => (
              <li
                key={`removed-${i}`}
                // WHY line-through + muted: removed bullets should visually recede —
                // they are yesterday's content, not today's story. Strikethrough is
                // a universal deletion convention.
                className="flex gap-1 leading-snug text-muted-foreground line-through"
              >
                <span className="shrink-0 font-mono">-</span>
                <span>{bullet.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────────── */}
      {!hasNew && !hasRemoved && (
        <p className="text-muted-foreground">No bullet-level changes found.</p>
      )}
    </div>
  );
}
