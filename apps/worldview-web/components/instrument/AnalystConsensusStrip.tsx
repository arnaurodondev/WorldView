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

      {/* ── Consensus data (all fields show "—" — data pending in Fundamentals type) */}
      {fundamentals && (
        <div>
          {/* Buy/Hold/Sell horizontal bar row */}
          {/* WHY h-6 (24px) for bar row: slightly taller than data rows to give the
              bar visual breathing room while staying below section header height. */}
          <div className="flex items-center h-6 px-2 gap-2 border-b border-border/30">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground shrink-0">
              RATINGS
            </span>

            {/* Segmented bar: 3 colored segments + total count */}
            {/* WHY show even at 0/0/0: establishes the visual structure so when
                data is available the layout doesn't shift. */}
            <div className="flex-1 flex h-3 rounded-[2px] overflow-hidden gap-px">
              {/* BUY segment — green */}
              <div
                className="bg-positive/50 h-full"
                style={{ flex: "1" }}
                title="BUY"
              />
              {/* HOLD segment — muted */}
              <div
                className="bg-muted h-full"
                style={{ flex: "1" }}
                title="HOLD"
              />
              {/* SELL segment — red */}
              <div
                className="bg-negative/50 h-full"
                style={{ flex: "1" }}
                title="SELL"
              />
            </div>

            {/* Analyst count */}
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
              — analysts
            </span>
          </div>

          {/* Price target row */}
          <div className="flex items-center h-[22px] px-2 gap-0 border-b border-border/30">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1">
              PRICE TARGET
            </span>
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
              HIGH —
            </span>
            <span className="px-1.5 text-border" aria-hidden>│</span>
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
              MED —
            </span>
            <span className="px-1.5 text-border" aria-hidden>│</span>
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
              LOW —
            </span>
          </div>

          {/* EPS estimate row */}
          <div className="flex items-center h-[22px] px-2 border-b border-border/30">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1">
              EPS ESTIMATE
            </span>
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
              $— —
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
