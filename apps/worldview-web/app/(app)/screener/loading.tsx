/**
 * app/(app)/screener/loading.tsx — Screener route segment loading state
 *
 * ROUND-3 (item 4): the previous centered <Loader2> spinner is replaced with a
 * SHAPE-MATCHED skeleton — a 36px toolbar band + header row + 20px-pitch
 * column-shaped data-row bars (ScreenerTableSkeleton). WHY: a spinner gives
 * zero layout preview, so the page visibly "popped" when the grid mounted; the
 * skeleton previews the exact chrome (toolbar height, header band, row pitch)
 * so the data swap-in is a fill, not a reflow.
 *
 * WHY 20px pitch (not the §15.10 22px token): the screener is locked to 20px
 * rows by the T-IA-14 architecture guard — see ScreenerTableSkeleton.tsx.
 *
 * WHY this stays a Server Component: ScreenerTableSkeleton is hook-free pure
 * markup, so the fallback streams instantly with the route shell — no client
 * bundle needed just to show placeholders.
 */

import { ScreenerTableSkeleton } from "@/components/screener/ScreenerTableSkeleton";

export default function Loading() {
  return (
    <div className="flex h-full flex-col bg-background">
      {/* Toolbar placeholder — mirrors ScreenerHeader's 36px band so the real
          toolbar replaces it 1:1 without vertical shift.
          ROUND-4 (item 4 — DS §6.2 sweep): all stub bars are STATIC bg-muted.
          Raw `animate-pulse` is banned for skeletons (§6.2); the route shell
          streams in well under the 2s threshold that would justify the
          `animate-skeleton-pulse` opt-in. */}
      <div className="flex h-[36px] shrink-0 items-center gap-2 border-b border-border px-3">
        <div className="h-2 w-32 rounded-[1px] bg-muted" />
        <div className="h-2 w-10 rounded-[1px] bg-muted" />
        <div className="ml-auto flex items-center gap-1">
          {/* Three 28px button stubs ≈ Filters / Saved Screens / Export. */}
          <div className="h-7 w-16 rounded-[2px] bg-muted" />
          <div className="h-7 w-20 rounded-[2px] bg-muted" />
          <div className="h-7 w-16 rounded-[2px] bg-muted" />
        </div>
      </div>

      {/* Chip-strip placeholder — mirrors FilterChipStrip's reserved 28px row. */}
      <div className="flex min-h-[28px] shrink-0 items-center border-b border-border bg-card px-3">
        <div className="h-2 w-20 rounded-[1px] bg-muted" />
      </div>

      {/* Header + 20px-pitch column-shaped rows. */}
      <ScreenerTableSkeleton rows={20} className="flex-1" />
    </div>
  );
}
