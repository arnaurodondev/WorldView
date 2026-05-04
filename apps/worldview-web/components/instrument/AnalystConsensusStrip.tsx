/**
 * components/instrument/AnalystConsensusStrip.tsx — Analyst consensus placeholder
 *
 * WHY THIS EXISTS: The Fundamentals tab needs an Analyst Consensus section above
 * the metrics grid. Analyst buy/hold/sell ratings and price targets are critical
 * for institutional decision-making (Bloomberg BEST function equivalent).
 *
 * WHY PLACEHOLDER (show "—" everywhere): The Fundamentals type does not yet include
 * analyst consensus fields (buy_count, hold_count, sell_count, price_target_median,
 * etc.). This component establishes the section structure and UX pattern so that
 * when S3/S9 adds the fields in a future wave, only the data binding needs updating.
 *
 * WHY ALWAYS RENDER (not return null when no data): The section header "ANALYST
 * CONSENSUS" should always appear in the Fundamentals tab to signal to analysts
 * that this data category is tracked — even if the specific values aren't available.
 * This is the Bloomberg convention: empty cells show "N.A." not disappear.
 *
 * WHO USES IT: FundamentalsTab.tsx (full-width section above the metrics grid)
 * DATA SOURCE: Props from FundamentalsTab (no independent fetch; data pending)
 * DESIGN REFERENCE: PRD-0031 §9 FundamentalsTab 9 sections, Wave 5
 */

// WHY no "use client": pure display component — no hooks, no browser APIs.

import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface AnalystConsensusStripProps {
  fundamentals: Fundamentals | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalystConsensusStrip({ fundamentals }: AnalystConsensusStripProps) {
  // ── Section header ─────────────────────────────────────────────────────────
  return (
    <div>
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ANALYST CONSENSUS
        </span>
      </div>

      {/* ── No fundamentals — InlineEmptyState ─────────────────────────────
          WHY not hide: see WHY ALWAYS RENDER above. The section should always
          exist in the fundamentals tab; null fundamentals shows a pending message. */}
      {!fundamentals && (
        <InlineEmptyState
          message="Analyst consensus data pending"
          className="px-2 py-1.5 text-[11px]"
        />
      )}

      {/* ── Consensus data — analyst fields not yet populated in Fundamentals type.
          WHY show "unavailable" row instead of broken equal-weight bars:
          Rendering three flex-1 bars with "—" counts looks like a broken chart.
          A single compact text row conveys the same "data pending" message without
          visual confusion. The data binding will be added when S3/S9 exposes
          buy_count / hold_count / sell_count. */}
      {fundamentals && (
        <div className="flex h-[22px] items-center px-2">
          <span className="text-[11px] text-muted-foreground">Analyst consensus data unavailable</span>
        </div>
      )}
    </div>
  );
}
