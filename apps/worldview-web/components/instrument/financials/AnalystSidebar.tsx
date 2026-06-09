/**
 * components/instrument/financials/AnalystSidebar.tsx — 7-panel composition shell (T-24)
 *
 * WHY THIS EXISTS (T-24 rewrite): PLAN-0089 W3 replaces the original 2-field
 * sidebar (consensus bar + 12-mo target) with a full 7-panel vertical stack.
 * The rewrite converts this file into a thin composition shell: each panel is
 * its own component with its own logic. The sidebar shell just orders them and
 * the border-b on each panel provides visual separation.
 *
 * WHY 240px width (was 280px): per §9.3 of the design spec. 240px gives the
 * left column ~60px more space at 1440px viewport — enough for an extra column
 * in PeerComparisonTable without truncating ticker symbols.
 *
 * PANEL ORDER (T-24 spec):
 *   1. CompanySnapshotPanel   — who/what the company is
 *   2. AnalystConsensusPanel  — consensus bucket bar
 *   3. TargetPricePanel       — 12-mo target + upside delta
 *   4. RevisionsPanel         — estimate revisions (shell only, v1.1 content)
 *   5. TargetsByAnalystPanel  — per-analyst targets (shell only, v1.1 content)
 *   6. BeatMissHistoryPanel   — historical EPS beat/miss sparkline
 *   7. AIBriefPanel           — AI-generated instrument brief (lazy-generate)
 *
 * WHY `w-full` (not `w-[240px]`): parent (FinancialsTab) controls the
 * fixed 240px width. The sidebar fills its container — keeps sizing concerns
 * at the layout level, not inside the sidebar.
 *
 * WHO USES IT: FinancialsTab.tsx (T-25) — rendered in the right column.
 * DATA SOURCE: All panels receive props or fetch independently via hooks.
 */

// WHY no "use client": this shell is purely compositional.
// Individual panels declare "use client" when they need browser APIs.

import { AnalystConsensusPanel } from "./sidebar/AnalystConsensusPanel";
import { TargetPricePanel } from "./sidebar/TargetPricePanel";
import { RevisionsPanel } from "./sidebar/RevisionsPanel";
import { TargetsByAnalystPanel } from "./sidebar/TargetsByAnalystPanel";
import { BeatMissHistoryPanel } from "./sidebar/BeatMissHistoryPanel";
import { AIBriefPanel } from "./sidebar/AIBriefPanel";
import { CompanySnapshotPanel } from "./sidebar/CompanySnapshotPanel";
import type { Instrument, Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalystSidebarProps {
  // Instrument identity for CompanySnapshotPanel (sector, industry, HQ, description).
  readonly instrument: Instrument | null | undefined;
  // WHY Fundamentals (not individual fields): passing the full Fundamentals
  // object avoids prop drilling 10+ fields through the sidebar shell. Each
  // panel reads only what it needs.
  readonly fundamentals: Fundamentals | null | undefined;
  // Current quote price for TargetPricePanel upside % calculation.
  readonly currentPrice: number | null | undefined;
  // entityId for AIBriefPanel (KG entity ID = instrumentId post-F2, Δ8).
  readonly entityId: string;
  // instrumentId for BeatMissHistoryPanel (S9 fundamentals endpoint key).
  readonly instrumentId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalystSidebar({
  instrument,
  fundamentals,
  currentPrice,
  entityId,
  instrumentId,
}: AnalystSidebarProps) {
  return (
    // WHY `overflow-y-auto h-full`: the sidebar must scroll independently from
    // the left column. Setting h-full matches the parent flex container height;
    // overflow-y-auto allows scroll when the 7 panels overflow.
    <aside
      className="flex h-full w-full flex-col overflow-y-auto border-l border-border bg-background"
      aria-label="Instrument analysis sidebar"
    >
      {/* 1. Company identity — always first so the analyst knows what they're
          looking at before reading any numbers. */}
      <CompanySnapshotPanel instrument={instrument} />

      {/* 2. Analyst consensus bar — primary sentiment signal. */}
      <AnalystConsensusPanel
        strongBuy={fundamentals?.analyst_strong_buy_count ?? null}
        buy={fundamentals?.analyst_buy_count ?? null}
        hold={fundamentals?.analyst_hold_count ?? null}
        sell={fundamentals?.analyst_sell_count ?? null}
        strongSell={fundamentals?.analyst_strong_sell_count ?? null}
      />

      {/* 3. 12-month price target + upside/downside delta. */}
      <TargetPricePanel
        targetPrice={fundamentals?.analyst_target_price ?? null}
        currentPrice={currentPrice ?? null}
        updatedAt={fundamentals?.updated_at ?? null}
      />

      {/* 4. Estimate revisions — v1.1 content, shell ships now (Δ18). */}
      <RevisionsPanel />

      {/* 5. Per-analyst price targets — v1.1 content, shell ships now (Δ17). */}
      <TargetsByAnalystPanel />

      {/* 6. Beat/miss history sparkline — self-fetching via earnings-history key. */}
      <BeatMissHistoryPanel instrumentId={instrumentId} />

      {/* 7. AI brief panel — lazy-generate flow (GET→POST→poll per Δ19). */}
      <AIBriefPanel entityId={entityId} />
    </aside>
  );
}
