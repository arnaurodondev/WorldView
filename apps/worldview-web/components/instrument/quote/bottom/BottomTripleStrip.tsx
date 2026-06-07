/**
 * components/instrument/quote/bottom/BottomTripleStrip.tsx
 * — 3-column bottom strip (PLAN-0099 W4)
 *
 * WHY THIS EXISTS: The Quote tab Wave D layout reserves 132px at the bottom of
 * the left column for three equal-width strips: Peers, Price Levels, and What's
 * Moving. This component composes them inside a 3-column grid.
 *
 * COLUMNS:
 *   1. Left  (1/3): PeersStrip — placeholder pending B-Q-1 backend endpoint
 *   2. Center (1/3): PriceLevelsStrip — placeholder pending B-Q-4 endpoint
 *   3. Right (1/3): WhatsMovingStrip — zero extra fetch, uses bundle.top_news
 *
 * WHY placeholders for left + center: The peers and price-levels endpoints
 * (B-Q-1 / B-Q-4) do not exist yet in S9. Building the placeholder cards now
 * means the frontend is ready to wire the data as soon as the backend lands —
 * we avoid a future "retrofit the layout" PR. The placeholder text is verbose
 * so future devs know exactly which backend wave to target.
 *
 * WHO USES IT: QuoteTab.tsx (Wave D layout).
 * LINE LIMIT: ≤ 100 LOC.
 */

// WHY no "use client": WhatsMovingStrip is already "use client" (uses useRouter);
// this orchestrator only composes layout — it contains no browser-only hooks.

import { WhatsMovingStrip } from "@/components/instrument/quote/bottom/WhatsMovingStrip";
import type { RankedNewsResponse } from "@/types/api";

// ── Placeholder ────────────────────────────────────────────────────────────────

/**
 * PendingPlaceholder — shown for columns whose backend endpoint doesn't exist yet.
 * WHY verbose label: makes it easy for the next developer to find the right
 * backend wave without reading the PR history.
 */
function PendingPlaceholder({ label, wave }: { label: string; wave: string }) {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Column header (matches WhatsMovingStrip header style) */}
      <div className="flex items-center h-[20px] px-2 border-b border-border/40 flex-shrink-0">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          {label}
        </span>
      </div>
      {/* Body: pending badge */}
      <div className="flex flex-1 items-center justify-center px-2">
        <p className="text-[9px] text-muted-foreground/50 text-center leading-[1.5]">
          Unavailable — backend endpoint pending ({wave})
        </p>
      </div>
    </div>
  );
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface BottomTripleStripProps {
  /** S3 instrument_id — used by future peers/price-levels fetch hooks. */
  instrumentId: string;
  /** KG entity_id — reserved for intelligence-link deep-dives. */
  entityId: string;
  /** Top-N ranked articles from bundle.top_news (zero extra fetch). */
  topNews: RankedNewsResponse | null | undefined;
  /** True while the bundle is loading — forwarded to WhatsMovingStrip. */
  isLoading?: boolean;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function BottomTripleStrip({
  // instrumentId and entityId are unused today (placeholders) but are received
  // so the parent doesn't need a prop-interface change when B-Q-1/B-Q-4 land.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  instrumentId: _instrumentId,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  entityId: _entityId,
  topNews,
  isLoading = false,
}: BottomTripleStripProps) {
  return (
    // WHY grid-cols-3: three equal columns at exactly 1/3 each.
    // WHY h-[132px]: fixed height so the chart column layout is predictable —
    // the flex layout above relies on this strip being exactly 132px tall.
    // WHY overflow-hidden: each column clips its own content; the strip never
    // expands the parent row.
    <div className="grid grid-cols-3 h-[132px] border-t border-border overflow-hidden">
      {/* Column 1: Peers — placeholder until B-Q-1 lands */}
      <div className="border-r border-border overflow-hidden">
        <PendingPlaceholder label="Peers" wave="B-Q-1" />
      </div>

      {/* Column 2: Price Levels — placeholder until B-Q-4 lands */}
      <div className="border-r border-border overflow-hidden">
        <PendingPlaceholder label="Price Levels" wave="B-Q-4" />
      </div>

      {/* Column 3: What's Moving — live from bundle.top_news */}
      {/* WHY zero extra fetch: topNews is bundle.top_news which arrives in the
          page-bundle round-trip. No dedicated useQuery here. */}
      <div className="overflow-hidden">
        <WhatsMovingStrip data={topNews} isLoading={isLoading} />
      </div>
    </div>
  );
}
