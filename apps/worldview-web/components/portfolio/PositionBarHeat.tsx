/**
 * components/portfolio/PositionBarHeat.tsx — h-12 weight × pnl% heat row
 * (PLAN-0088 Wave E E-4).
 *
 * One row, vertical bars per holding:
 *   - bar WIDTH = position weight (so the eye sees relative concentration)
 *   - bar HEIGHT = signed pnl% (positive grows up; negative grows down)
 *   - bar COLOR = sign of pnl% (green / red, muted shades)
 *
 * Inspired by Finviz portfolio bar — a single horizontal strip that
 * communicates winners/losers + concentration in one glance, without the
 * vertical real estate of a treemap.
 *
 * DATA: holdings + live quotes already loaded by the parent (HoldingsTab).
 * No additional fetch — the parent passes enrichedHoldings + quotes as
 * props, mirroring the existing SemanticHoldingsTable contract. WHY pass
 * computed numbers (not refetch): the parent already pays the server-
 * side cost; sharing eliminates double-rendering and ensures the bar
 * row reflects exactly the same numbers as the table below it.
 *
 * WHO USES IT: HoldingsTab below the holdings table.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-4, audit §2 wireframe row R-11.
 */

"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";
import type { Holding, BatchQuoteResponse } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface PositionBarHeatProps {
  /** Already-enriched holdings rows (ticker/name resolved by the parent). */
  holdings: Holding[];
  /** Live quote map keyed by instrument_id (same shape parent uses for table). */
  quotes: BatchQuoteResponse["quotes"];
  /** Total portfolio value — denominator for weight calculation. */
  totalValue: number;
}

// ── Component ────────────────────────────────────────────────────────────────

export function PositionBarHeat({
  holdings,
  quotes,
  totalValue,
}: PositionBarHeatProps) {
  // Compute per-position weight + pnl% in one pass. Sorted by weight desc
  // so the largest positions are leftmost — matches the natural "biggest
  // bets first" reading order traders expect.
  const bars = useMemo(() => {
    if (totalValue <= 0 || holdings.length === 0) return [];
    return holdings
      .map((h) => {
        const quote = quotes[h.instrument_id];
        const livePrice = quote?.price ?? h.average_cost;
        const value = livePrice * h.quantity;
        const weight = (value / totalValue) * 100;
        const pnlPct =
          h.average_cost > 0
            ? ((livePrice - h.average_cost) / h.average_cost) * 100
            : 0;
        return {
          ticker: h.ticker || "—",
          weight,
          pnlPct,
        };
      })
      .filter((b) => b.weight > 0)
      .sort((a, b) => b.weight - a.weight);
  }, [holdings, quotes, totalValue]);

  if (bars.length === 0) {
    return (
      <div className="flex h-12 items-center px-3 border-b border-border bg-card font-mono text-[10px] text-muted-foreground uppercase tracking-[0.08em]">
        POSITION HEAT — no positions
      </div>
    );
  }

  // We render the bars on a [-100%, +100%] vertical axis centred at the
  // mid-point of the row so positive bars grow up and negative bars
  // grow down. The actual pixel-height clamp is to ±100% pnl — any bigger
  // and the bar is just "off the chart"; visually saturating the bar is
  // more honest than rescaling away the signal of the smaller positions.
  const ROW_HEIGHT = 40; // total bar zone (h-12 row minus label band)
  const HALF = ROW_HEIGHT / 2;
  // Horizontal bar widths are proportional to weight; we cap each bar at
  // 64 px (so a 90%-weight position doesn't visually swamp the row) and
  // floor at 8 px (so a 0.5% position is still clickable / visible).
  const widthFor = (weight: number) =>
    Math.max(8, Math.min(64, Math.round(weight * 0.8)));

  return (
    <div className="h-12 border-b border-border bg-card flex flex-col">
      {/* Tiny caption — keeps consistency with other strips in the cluster. */}
      <div className="h-3 px-3 flex items-center text-[9px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
        POSITION HEAT — width = weight, height = pnl%, colour = sign
      </div>
      {/* Bar row. WHY items-center: bars are positioned via inline transform
          so the centre line is the y=0 reference for positive/negative growth. */}
      <div
        className="flex-1 flex items-center gap-1 px-3 overflow-hidden"
        style={{ height: ROW_HEIGHT }}
      >
        {bars.map((bar) => {
          // Bar height = clamped pnlPct mapped onto HALF pixels.
          const clamped = Math.max(-100, Math.min(100, bar.pnlPct));
          const barHeight = Math.max(2, Math.abs(clamped) * (HALF / 100));
          const positive = clamped >= 0;
          const w = widthFor(bar.weight);
          return (
            <div
              key={bar.ticker}
              title={`${bar.ticker} · weight ${bar.weight.toFixed(1)}% · pnl ${bar.pnlPct.toFixed(1)}%`}
              className="flex flex-col items-center justify-center shrink-0"
              style={{ width: w }}
            >
              {/* Top half — only paints when positive. */}
              <div
                style={{
                  height: positive ? barHeight : 0,
                  width: "100%",
                }}
                className={cn(positive && "bg-positive/60")}
              />
              {/* Centre divider — 1 px hairline so the chart has an obvious
                  zero line. WHY divide-y feeling: keeps the visual anchored. */}
              <div className="h-px w-full bg-border" />
              {/* Bottom half — only paints when negative. */}
              <div
                style={{
                  height: positive ? 0 : barHeight,
                  width: "100%",
                }}
                className={cn(!positive && "bg-negative/60")}
              />
              {/* WHY w >= 18 guard: at 8–17px a 4-char label overflows into adjacent
                  bars. Only render when the bar is wide enough to contain the text.
                  The hover tooltip (title=) always shows the full ticker. */}
              {w >= 18 && (
                <div className="text-[8px] font-mono text-muted-foreground mt-px tabular-nums leading-none overflow-hidden whitespace-nowrap" style={{ maxWidth: w }}>
                  {bar.ticker.slice(0, 4)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
