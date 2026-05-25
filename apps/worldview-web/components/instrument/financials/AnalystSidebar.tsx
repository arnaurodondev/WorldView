/**
 * components/instrument/financials/AnalystSidebar.tsx — 7-panel right sidebar shell
 *
 * WHY THIS EXISTS (T-24 rewrite): W3 expands the single-block analyst panel into
 * 7 distinct panels covering the full analyst opinion surface: consensus bar,
 * 12-month target, estimate revisions, per-firm targets, beat/miss history, AI
 * brief, and company snapshot. This component is the thin orchestration shell —
 * it receives the minimum props and delegates rendering to the individual panel
 * components in sidebar/.
 *
 * WHY 240px (not 280px): T-25 narrows the sidebar from 280px to 240px to give
 * the left column more horizontal space for the 6-column DenseMetricsGrid and
 * the wide InsiderTransactionsTable. 240px is sufficient for the panel titles
 * and tabular data at 11px monospace.
 *
 * WHY NO DATA FETCHING HERE: All panel-level data fetching is in the individual
 * panel components (BeatMissHistoryPanel, AIBriefPanel, CompanySnapshotPanel).
 * Props passed here come from useFinancialsTabData (already in FinancialsTab's
 * scope) — no new fetches in this shell.
 *
 * WHO USES IT: FinancialsTab.tsx (right column, T-25 wiring).
 * DATA SOURCE: Props from FinancialsTab (useFinancialsTabData results).
 */

// WHY no "use client": this shell has no hooks — all interactive panels are
// individually marked "use client". Server-safe for future RSC migration.

import { AnalystConsensusPanel } from "@/components/instrument/financials/sidebar/AnalystConsensusPanel";
import { TargetPricePanel } from "@/components/instrument/financials/sidebar/TargetPricePanel";
import { RevisionsPanel } from "@/components/instrument/financials/sidebar/RevisionsPanel";
import { TargetsByAnalystPanel } from "@/components/instrument/financials/sidebar/TargetsByAnalystPanel";
import { BeatMissHistoryPanel } from "@/components/instrument/financials/sidebar/BeatMissHistoryPanel";
import { AIBriefPanel } from "@/components/instrument/financials/sidebar/AIBriefPanel";
import { CompanySnapshotPanel } from "@/components/instrument/financials/sidebar/CompanySnapshotPanel";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

export interface AnalystSidebarProps {
  instrumentId: string;
  fundamentals: Fundamentals | null | undefined;
  snapshot: FundamentalsSnapshot | null | undefined;
}

export function AnalystSidebar({
  instrumentId,
  fundamentals,
}: AnalystSidebarProps) {
  // WHY not spreading analyst fields: passing the entire fundamentals object
  // keeps this shell thin and avoids a 10-field prop explosion when the panel
  // interface expands. Each panel destructures what it needs.
  return (
    <aside
      className="flex h-full w-full flex-col overflow-y-auto border-l border-border bg-background"
      aria-label="Analyst sidebar"
    >
      {/* Panel 1 — Analyst consensus bucket bar + N analysts subline */}
      <AnalystConsensusPanel
        strongBuy={fundamentals?.analyst_strong_buy_count ?? null}
        buy={fundamentals?.analyst_buy_count ?? null}
        hold={fundamentals?.analyst_hold_count ?? null}
        sell={fundamentals?.analyst_sell_count ?? null}
        strongSell={fundamentals?.analyst_strong_sell_count ?? null}
      />

      {/* Panel 2 — 12-month consensus price target with upside chip */}
      <TargetPricePanel
        targetPrice={fundamentals?.analyst_target_price ?? null}
        // WHY no currentPrice: Quote data is in the page bundle but not wired
        // into FinancialsTab's prop surface. Upside chip hides gracefully when
        // currentPrice is absent. A future T-25 pass can thread it through.
        currentPrice={null}
        updatedAt={fundamentals?.updated_at ?? null}
      />

      {/* Panel 3 — Estimate revisions stub (pending data source) */}
      <RevisionsPanel />

      {/* Panel 4 — Per-firm targets stub (pending data source) */}
      <TargetsByAnalystPanel />

      {/* Panel 5 — EPS beat/miss sparkline (self-fetching, 24h cache) */}
      <BeatMissHistoryPanel instrumentId={instrumentId} />

      {/* Panel 6 — AI brief bullets + expand dialog */}
      <AIBriefPanel instrumentId={instrumentId} />

      {/* Panel 7 — Company snapshot (sector/industry/country/description) */}
      <CompanySnapshotPanel instrumentId={instrumentId} />
    </aside>
  );
}
