/**
 * components/intelligence/WeirdnessBreakdown.tsx — shared "weirdness" sub-score UI
 * (PLAN-0112 T-5-03)
 *
 * WHY THIS EXISTS:
 * Three surfaces render the SAME four interpretable sub-scores behind the
 * "weirdness" headline metric: the global WeirdConnectionsFeed, the pairwise
 * PathBetweenPanel, and the per-entity PathsTab / PathInsightsBlock. Centralising
 * the labels, ordering, colour mapping, and the null-guard here means a relabel or
 * format tweak happens in exactly ONE place — and every surface stays consistent.
 *
 * WHY a compact horizontal mini-bar layout (not a table):
 * These breakdowns appear INSIDE dense path cards in a finance terminal. A 4-cell
 * inline row of tiny labelled bars reads at a glance without stealing vertical
 * space from the path visualisation, which is the focal element of each card.
 *
 * THE FOUR SUB-SCORES (all 0–1, see types/intelligence.ts WeirdnessSubScores):
 *   - reliability      — harmonic mean of edge confidences (path trustworthiness)
 *   - unexpectedness   — topological surprise (non-hub endpoints score high)
 *   - semantic_distance— how far apart the endpoints are in embedding space
 *   - novelty          — fraction of edges first seen recently
 *
 * DESIGN: Midnight Pro palette. We deliberately use the *_token classes that the
 * project guarantees actually PAINT — `bg-primary`, `bg-muted`, `text-muted-
 * foreground`, `text-foreground` — to avoid the known `hsl(var())` no-paint bug
 * class (a CSS var that resolves to an unpainted/zero value). No raw hsl(var(...))
 * inline styles for colour; width is the only inline style (it is a computed %).
 */

"use client";
// WHY "use client": rendered inside client path-card components. It has no
// browser-only API itself, but keeping it a client component avoids the
// server/client boundary warning when imported by "use client" parents.

import { cn } from "@/lib/utils";

// ── Sub-score descriptor ──────────────────────────────────────────────────────

/**
 * The four sub-scores in fixed display order, with a short label and a one-line
 * tooltip. WHY a const array (not inline JSX): a single source of truth for the
 * order + copy that the map below iterates — adding/renaming a sub-score is a
 * one-line edit here.
 */
const SUB_SCORES = [
  {
    key: "reliability",
    label: "REL",
    title: "Reliability — harmonic mean of edge confidences (higher = more trustworthy path)",
  },
  {
    key: "unexpectedness",
    label: "UNEXP",
    title: "Unexpectedness — topological surprise; paths through non-hub entities score higher",
  },
  {
    key: "semantic_distance",
    label: "DIST",
    title: "Semantic distance — how far apart the two endpoints are in embedding space",
  },
  {
    key: "novelty",
    label: "NEW",
    title: "Novelty — fraction of the path's edges first observed within the recency window",
  },
] as const;

// ── Props ─────────────────────────────────────────────────────────────────────

export interface WeirdnessBreakdownProps {
  /**
   * The four sub-scores. Each may be a number (0–1), null, or undefined.
   * WHY accept null/undefined: old `path_insights` rows (pre-PLAN-0112 migration)
   * carry null sub-scores. We render those cells as "—" rather than a misleading
   * zero-width bar, so the analyst can tell "unscored" apart from "scored low".
   */
  reliability?: number | null;
  unexpectedness?: number | null;
  semantic_distance?: number | null;
  novelty?: number | null;
  /** Optional extra classes for the wrapper (spacing in the parent card). */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WeirdnessBreakdown({
  reliability,
  unexpectedness,
  semantic_distance,
  novelty,
  className,
}: WeirdnessBreakdownProps) {
  // Map the prop bag to a lookup so the descriptor loop can read by key.
  const values: Record<string, number | null | undefined> = {
    reliability,
    unexpectedness,
    semantic_distance,
    novelty,
  };

  return (
    <div
      className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", className)}
      aria-label="Weirdness sub-scores"
    >
      {SUB_SCORES.map(({ key, label, title }) => {
        const raw = values[key];
        // Guard: treat null/undefined/NaN as "unscored" → "—" cell.
        const scored = typeof raw === "number" && Number.isFinite(raw);
        // Clamp to [0,1] then to a 0–100 width % for the mini-bar.
        const pct = scored ? Math.round(Math.min(1, Math.max(0, raw)) * 100) : 0;

        return (
          <div
            key={key}
            className="flex items-center gap-1"
            title={title}
          >
            {/* Sub-score label — tiny uppercase mono, terminal density. */}
            <span className="text-[8px] font-mono uppercase tracking-wider text-muted-foreground">
              {label}
            </span>

            {/* Mini progress bar (track + fill). bg-muted/bg-primary both paint. */}
            <div
              className="h-1 w-8 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={scored ? pct : undefined}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${label}: ${scored ? `${pct}%` : "unscored"}`}
            >
              {scored && (
                <div
                  className="h-full rounded-full bg-primary"
                  // WHY inline width: it is a computed percentage, the one thing
                  // Tailwind utility classes cannot express dynamically.
                  style={{ width: `${pct}%` }}
                />
              )}
            </div>

            {/* Numeric readout, or "—" when unscored (back-compat null rows). */}
            <span className="w-6 text-right text-[9px] font-mono tabular-nums text-foreground/70">
              {scored ? pct : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
