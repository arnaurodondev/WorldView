/**
 * components/screener/HeatCell.tsx — Score cell with 7-step heat color scale
 *
 * WHY THIS EXISTS: The screener's "Score" column needs a visual indicator that
 * maps the S6 market_impact_score (0.0–1.0) to the 7-step heat scale defined
 * in the design system. A plain number isn't enough — finance users need the
 * color signal to scan rows quickly, just like Finviz's screener or Bloomberg's
 * RAG (Red/Amber/Green) flagging system.
 *
 * WHY THIS SCALE MAPPING (score - 0.5) * 6:
 * The heatCellColor function expects a percent-like value in [-3, +3].
 * score=0.0 → -3 (worst → deep red)
 * score=0.5 → 0  (neutral → grey)
 * score=1.0 → +3 (best → deep teal)
 * This maps the full [0,1] score range linearly onto the 7-step palette.
 *
 * WHO USES IT: app/(app)/screener/page.tsx → results table Score column
 * DATA SOURCE: ScreenerResult.market_impact_score (PRD-0020, S6 signal score)
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md HeatCell, PRD-0027 §6.5 canvas
 */

import { memo } from "react";
import { heatCellColor } from "@/lib/utils";

// ── Props ──────────────────────────────────────────────────────────────────────

interface HeatCellProps {
  /** Score in 0.0–1.0 range from S6 market_impact_score. Null = no data. */
  score: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * HeatCell — renders a compact colored rectangle containing the score as 0–100.
 *
 * Layout: fixed-width pill so all score cells align perfectly in the table column.
 * WHY inline style for colors: heatCellColor returns hex strings, not Tailwind
 * classes — lightweight-charts and other non-Tailwind contexts also use these
 * same hex values, so the source of truth stays in utils.ts, not CSS files.
 */
// WHY inline hex (not Tailwind classes): heatCellColor() returns hex values because
// these same colors are shared with lightweight-charts and other non-Tailwind contexts.
// The hex source of truth lives in lib/utils.ts heatCellColor() — see V-1.4.
//
// PLAN-0059 G-3: HeatCell is a high-frequency leaf — rendered once per
// screener row + once per dashboard sector tile. Memoising on `score`
// (the only prop) prevents re-running heatCellColor() / Math.round() when
// other table state (sort, scroll, filter) changes but the score for a
// given row didn't. Verified-stable: heatCellColor is pure, the prop is
// a primitive, and there are no callbacks in the prop set.
function HeatCellInner({ score }: HeatCellProps) {
  // ── Null / no-data case ────────────────────────────────────────────────────
  if (score === null || score === undefined) {
    // WHY neutral palette: user should see "no data" not "bad score" — grey
    // communicates absence, red communicates negative signal (important distinction)
    return (
      <span
        className="inline-flex h-6 w-12 items-center justify-center rounded-[2px] text-[11px] font-mono font-medium tabular-nums"
        style={{ backgroundColor: "#1A2030", color: "#6B7585" }}
        title="No score available"
        aria-label="Score unavailable"
      >
        —
      </span>
    );
  }

  // ── Map score [0,1] → heat scale input [-3,+3] ────────────────────────────
  // WHY this formula: heatCellColor expects changePct-like values in [-3, +3].
  // Mapping: score=0→-3, score=0.5→0, score=1→+3 (linear, covers full palette)
  const heatInput = (score - 0.5) * 6;
  const { background, color } = heatCellColor(heatInput);

  // ── Display value: integer 0–100 ──────────────────────────────────────────
  // WHY Math.round: avoids showing "74.9999..." for near-integer scores
  const displayScore = Math.round(score * 100);

  return (
    <span
      className="inline-flex h-6 w-12 items-center justify-center rounded-[2px] text-[11px] font-mono font-medium tabular-nums"
      style={{ backgroundColor: background, color }}
      title={`Signal score: ${displayScore}/100`}
      aria-label={`Signal score ${displayScore} out of 100`}
    >
      {displayScore}
    </span>
  );
}

// PLAN-0059 G-3: memo'd export. The inner is named HeatCellInner so React
// DevTools shows the memoised component as just "HeatCell".
export const HeatCell = memo(HeatCellInner);
HeatCell.displayName = "HeatCell";
