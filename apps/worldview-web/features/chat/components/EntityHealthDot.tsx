/**
 * features/chat/components/EntityHealthDot.tsx — 8px health score indicator.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block D, T-15):
 *   The PLAN-0080 KG scheduler ships a per-entity `health_score` (0..1)
 *   summarising how well-populated an entity profile is (description,
 *   sector, classification, narrative, recent fundamentals, etc.). The
 *   chat right-rail surfaces the active entity card — analysts need a
 *   single-glance signal of "is this entity well-grounded or sparse?".
 *   A tiny coloured dot is the most data-dense way to convey that:
 *   8px x 8px, zero text, deterministic colour. Hover surfaces the
 *   numeric breakdown via a Radix Tooltip.
 *
 * DATA SOURCE: caller passes `score` (and optional `dataCompleteness`)
 *   from a cached `get_entity_health` tool result captured during a turn.
 *   This component does NOT fetch — it is a pure visual badge.
 *
 * COLOUR RAMP (mirrors Block C `ContradictionStrip` thresholds at 0.7 /
 *   0.4 so the visual language is consistent across rails):
 *     - score ≥ 0.7  → bg-positive  (green)  — well-grounded
 *     - 0.4 ≤ s < 0.7 → bg-warning  (amber)  — partial coverage
 *     - score < 0.4  → bg-negative  (red)    — sparse / risky
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §3.4 (entity card +
 *   8px health dot) + docs/ui/DESIGN_SYSTEM.md §0.3 semantic palette.
 */

"use client";

// "use client" because Radix Tooltip relies on hover/focus DOM events that
// are not available during SSR. The dot itself would render fine on the
// server but the tooltip would never trigger.

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Threshold breakpoints — identical to ContradictionStrip severity rules.
// If these ever change, update BOTH files (or extract to a shared module).
const HEALTH_GOOD_MIN = 0.7;
const HEALTH_WARN_MIN = 0.4;

interface EntityHealthDotProps {
  /** Health score in [0, 1]. Out-of-range inputs are clamped at render time. */
  readonly score: number;
  /**
   * Optional field-coverage breakdown — when present, the tooltip shows
   * `{score} · {populated}/{total}`. When absent the tooltip shows only
   * the score (still useful, just less informative).
   */
  readonly dataCompleteness?: { populated: number; total: number };
}

/**
 * colourClass — maps a clamped score to a Tailwind semantic token. Defined
 * at module scope (not inline) so the comparison logic stays trivial and
 * the Tailwind classes are statically extractable by the JIT compiler.
 */
function colourClass(score: number): string {
  if (score >= HEALTH_GOOD_MIN) return "bg-positive";
  if (score >= HEALTH_WARN_MIN) return "bg-warning";
  return "bg-negative";
}

/**
 * EntityHealthDot — see file header. The dot is 8x8 px (`h-2 w-2`) and
 * inline-flex-friendly: the parent decides where it sits in the entity
 * card row.
 */
export function EntityHealthDot({ score, dataCompleteness }: EntityHealthDotProps) {
  // Clamp before colour selection AND before display, so a backend bug
  // that ships `score = 1.7` cannot render an off-palette dot or a "170%"
  // tooltip. NaN guard short-circuits to the worst-case bucket.
  const safeScore = Number.isFinite(score) ? Math.max(0, Math.min(1, score)) : 0;
  const completenessLabel = dataCompleteness
    ? `${dataCompleteness.populated}/${dataCompleteness.total}`
    : null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          // role=img + aria-label so screen readers announce the dot's
          // semantic meaning instead of trying to describe an empty span.
          role="img"
          aria-label={`Entity health score ${safeScore.toFixed(2)}${
            completenessLabel ? `, completeness ${completenessLabel}` : ""
          }`}
          data-cell
          className={`inline-block h-2 w-2 rounded-full ${colourClass(safeScore)}`}
        />
      </TooltipTrigger>
      <TooltipContent>
        <span className="font-mono text-[10px] tabular-nums">
          {safeScore.toFixed(2)}
          {completenessLabel ? ` · ${completenessLabel}` : null}
        </span>
      </TooltipContent>
    </Tooltip>
  );
}
