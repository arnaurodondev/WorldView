/**
 * sidebar/AnalystConsensusPanel.tsx — Analyst consensus bucket bar
 *
 * WHY THIS EXISTS (T-17): The top-of-sidebar panel condenses Wall Street's
 * consensus into a single colour bar (Buy / Hold / Sell collapse of the 5
 * EODHD buckets) with a colour-coded textual breakdown.
 *
 * WHY REUSE AnalystMiniBar: T-B-02 owns the palette, null handling, and the
 * bucket-collapse logic. Duplicating it here would fragment the design
 * system and add two test surfaces for the same visual invariant.
 *
 * WAVE-2 NOTE: the panel's own "{N} analysts" subline was REMOVED — the
 * Wave-2 AnalystMiniBar now renders the sample size itself (right-aligned
 * "{total} analysts"), so the panel line had become a duplicate. The bar
 * also owns the zero-coverage state ("No analyst coverage").
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: analyst_*_count fields from Fundamentals (pre-passed by AnalystSidebar).
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

import { AnalystMiniBar } from "@/components/instrument/quote/metrics/AnalystMiniBar";

interface AnalystConsensusPanelProps {
  strongBuy: number | null;
  buy: number | null;
  hold: number | null;
  sell: number | null;
  strongSell: number | null;
}

export function AnalystConsensusPanel({
  strongBuy,
  buy,
  hold,
  sell,
  strongSell,
}: AnalystConsensusPanelProps) {
  return (
    <div className="flex flex-col gap-2 px-2 py-2 border-b border-border">
      {/* Round-3 item 2: label-level accent bar — uniform Round-1 section
          marker (label-level because padded sidebar
          panels have no dedicated header row to tint). */}
      <span className="border-l-2 border-l-primary pl-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        ANALYST CONSENSUS
      </span>
      {/* The bar owns BOTH the breakdown and the right-aligned sample size
          ("{N} analysts") since Wave-2 — nothing else to render here. */}
      <AnalystMiniBar
        strongBuy={strongBuy}
        buy={buy}
        hold={hold}
        sell={sell}
        strongSell={strongSell}
      />
    </div>
  );
}
