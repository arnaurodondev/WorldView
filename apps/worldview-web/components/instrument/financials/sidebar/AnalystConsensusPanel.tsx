/**
 * sidebar/AnalystConsensusPanel.tsx — Analyst consensus bucket bar + analyst count
 *
 * WHY THIS EXISTS (T-17): The top-of-sidebar panel condenses Wall Street's
 * consensus into a single 5-bucket color bar (Strong Buy → Strong Sell). The
 * "N analysts" subline gives context for the bar's statistical weight — a
 * bar from 2 analysts reads differently than one from 45.
 *
 * WHY REUSE AnalystMiniBar: T-B-02 owns the palette, null handling, and the
 * Bloomberg 5-bucket color gradient. Duplicating it here would fragment the
 * design system and add two test surfaces for the same visual invariant.
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
  const total =
    (strongBuy ?? 0) + (buy ?? 0) + (hold ?? 0) + (sell ?? 0) + (strongSell ?? 0);

  return (
    <div className="flex flex-col gap-2 px-2 py-2 border-b border-border">
      {/* Round-3 item 2: label-level accent bar — uniform Round-1 section
          marker (see RevisionsPanel for the full rationale). */}
      <span className="border-l-2 border-l-primary pl-1.5 text-[9px] uppercase tracking-widest text-muted-foreground/70">
        ANALYST CONSENSUS
      </span>
      <AnalystMiniBar
        strongBuy={strongBuy}
        buy={buy}
        hold={hold}
        sell={sell}
        strongSell={strongSell}
      />
      {total > 0 && (
        <span className="text-[10px] text-muted-foreground/60 font-mono tabular-nums">
          {total} analyst{total !== 1 ? "s" : ""}
        </span>
      )}
    </div>
  );
}
