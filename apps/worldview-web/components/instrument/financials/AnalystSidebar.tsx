/**
 * components/instrument/financials/AnalystSidebar.tsx — Right-rail analyst panel
 *
 * WHY THIS EXISTS: PRD-0088 §6.8 specifies a fixed 280px right column on the
 * Financials tab that surfaces the most decision-relevant artefact: Wall-Street
 * recommendation consensus + 12-month price target (Bloomberg BEST/EE; Finviz
 * "Recom" pill). Sits side-by-side with the metrics grid so the analyst can
 * compare company truth (10-K numbers, left) against market opinion (right)
 * without scrolling.
 *
 * COMPOSITION (top → bottom): "ANALYST CONSENSUS" header → <AnalystMiniBar/>
 * (T-B-02 reuse) → consensus 12-mo target (font-mono, large) → updated-at
 * timestamp pinned to bottom.
 *
 * WHY REUSE AnalystMiniBar (do not duplicate): T-B-02 already owns the 5-bucket
 * stacked recommendation bar with the Bloomberg palette + null-handling logic.
 * Duplicating it would fragment the design system and double the test surface.
 *
 * WHO USES IT: FinancialsTab.tsx (right column).
 * DATA SOURCE: Props from useFinancialsTabData (T-A-03).
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

import { AnalystMiniBar } from "@/components/instrument/quote/metrics/AnalystMiniBar";
import { formatPrice } from "@/lib/utils";

export interface AnalystSidebarProps {
  // 5 bucket counts — null = EODHD never returned a value (no coverage).
  // Passed verbatim to AnalystMiniBar which owns the null/empty rendering.
  readonly strongBuy: number | null;
  readonly buy: number | null;
  readonly hold: number | null;
  readonly sell: number | null;
  readonly strongSell: number | null;
  // Consensus 12-mo target (USD); null → "—" so layout height stays stable.
  readonly targetPrice: number | null;
  // ISO-8601 UTC; rendered date-only at the bottom for data-freshness signal.
  readonly updatedAt: string | null;
}

export function AnalystSidebar({
  strongBuy,
  buy,
  hold,
  sell,
  strongSell,
  targetPrice,
  updatedAt,
}: AnalystSidebarProps) {
  // WHY `flex flex-col h-full`: parent gives us w-[280px] + full tab height.
  // Filling vertically lets the timestamp pin to the bottom (mt-auto) even
  // when the bar + target take <50% of the column — keeps the section anchored.
  return (
    <aside
      className="flex h-full w-full flex-col border-l border-border bg-background"
      aria-label="Analyst consensus"
    >
      {/* Section header — 24px terminal-row baseline used across the app */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ANALYST CONSENSUS
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-2">
        {/* Reuse T-B-02. AnalystMiniBar handles null counts + empty-state. */}
        <AnalystMiniBar
          strongBuy={strongBuy}
          buy={buy}
          hold={hold}
          sell={sell}
          strongSell={strongSell}
        />

        {/* WHY a dedicated block (not inline in the bar): the target price is
            the most-cited number on the page. Caption + big mono digit makes
            it scannable in <200ms — the "first glance" budget on a terminal. */}
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
            12-MO Target
          </span>
          <span className="font-mono text-[18px] leading-tight text-foreground tabular-nums">
            {targetPrice != null ? formatPrice(targetPrice) : "—"}
          </span>
        </div>

        {/* WHY mt-auto: pins the timestamp to the bottom regardless of upper
            block heights. WHY date-only slice (not full ISO): minute precision
            adds no decision value at this density. */}
        {updatedAt && (
          <div className="mt-auto pt-2 text-[10px] text-muted-foreground/70">
            <span>Updated {updatedAt.slice(0, 10)}</span>
          </div>
        )}
      </div>
    </aside>
  );
}
