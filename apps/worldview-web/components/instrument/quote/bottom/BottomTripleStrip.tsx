/**
 * components/instrument/quote/bottom/BottomTripleStrip.tsx
 * — 3-column layout wrapper for the bottom strip (W5-T-22)
 *
 * WHY THIS EXISTS: the plan calls for Peers / PriceLevels / WhatsMoving in a
 *   horizontal 3-column layout below the right-rail scroll area. Separating the
 *   layout from the 3 data components keeps each child independently testable.
 *
 * COLUMNS:
 *   1. PeersStrip        — peers (top 5, fetch required)
 *   2. PriceLevelsStrip  — floor pivot levels (fetch required)
 *   3. WhatsMovingStrip  — recent entity news (from bundle, zero extra fetch)
 *
 * DESIGN:
 *   - `grid grid-cols-3 divide-x divide-[hsl(var(--border-subtle))]` — equal cols.
 *   - Border-t separator from the MetricsTable block above. No `rounded-*` (Δ3).
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass).
 * LINE LIMIT: ≤ 60 LOC (pure layout wrapper).
 */

// WHY no "use client": sub-components carry their own client markers.

import type { PeersResponse, PriceLevelsResponse, RankedNewsResponse } from "@/types/api";
import { PeersStrip } from "./PeersStrip";
import { PriceLevelsStrip } from "./PriceLevelsStrip";
import { WhatsMovingStrip } from "./WhatsMovingStrip";

interface BottomTripleStripProps {
  peers: PeersResponse | undefined;
  priceLevels: PriceLevelsResponse | undefined;
  topNews: RankedNewsResponse | null | undefined;
  currentPrice?: number | null;
  isLoadingPeers?: boolean;
  isLoadingLevels?: boolean;
  isErrorPeers?: boolean;
  isErrorLevels?: boolean;
}

export function BottomTripleStrip({
  peers,
  priceLevels,
  topNews,
  currentPrice,
  isLoadingPeers,
  isLoadingLevels,
  isErrorPeers,
  isErrorLevels,
}: BottomTripleStripProps) {
  return (
    // WHY border-t (Δ6): hairline group divider above the bottom strip.
    // WHY grid grid-cols-3 divide-x: equal-width columns with vertical hairlines.
    <div className="border-t border-[hsl(var(--border-subtle))] grid grid-cols-3 divide-x divide-[hsl(var(--border-subtle))]">
      <PeersStrip data={peers} isLoading={isLoadingPeers} isError={isErrorPeers} />
      <PriceLevelsStrip
        data={priceLevels}
        isLoading={isLoadingLevels}
        isError={isErrorLevels}
        currentPrice={currentPrice}
      />
      <WhatsMovingStrip data={topNews} />
    </div>
  );
}
