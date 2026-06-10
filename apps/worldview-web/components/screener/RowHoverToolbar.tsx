/**
 * components/screener/RowHoverToolbar.tsx — floating 3-button row action overlay
 *
 * WHY THIS EXISTS: Row-level actions (watch, alert, compare) need quick access
 * without consuming a permanent column slot. The toolbar appears as a fixed overlay
 * at the right edge of the hovered row, fading in after 100ms.
 *
 * WHY position:fixed (not absolute): AG Grid rows are virtualised — position:absolute
 * inside the grid container would scroll with the grid body. Fixed positioning anchors
 * to the viewport edge so the toolbar always appears at the visible row position.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (rendered outside AgGridBase)
 */

"use client";

import { Bell, BookmarkPlus, GitCompare } from "lucide-react";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface RowHoverToolbarProps {
  /** Screen-space bounding rect of the hovered AG Grid row. */
  rowRect: DOMRect;
  /** The hovered instrument. */
  ticker: string;
  instrumentId: string;
  /** Callbacks — page handles the actual mutations/state. */
  onWatch: (instrumentId: string) => void;
  onAlert: (instrumentId: string) => void;
  onCompare: (ticker: string) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RowHoverToolbar({
  rowRect,
  ticker,
  instrumentId,
  onWatch,
  onAlert,
  onCompare,
}: RowHoverToolbarProps) {
  // Vertically centre the 20px toolbar inside the hovered row.
  // ROUND-3 item 1: buttons shrunk h-6 (24px) → h-5 (20px) because the grid
  // adopted rowHeight={20} — a 24px overlay visually bled onto the rows above
  // and below the hovered one. rowRect.height keeps this correct if the row
  // height ever changes again.
  const top = rowRect.top + (rowRect.height - 20) / 2;

  return (
    <div
      role="toolbar"
      aria-label={`Actions for ${ticker}`}
      className="fixed z-50 flex items-center gap-0.5 pointer-events-auto animate-in fade-in-0 duration-100"
      style={{ top, right: 8 }}
    >
      <button
        type="button"
        aria-label={`Add ${ticker} to watchlist`}
        onClick={() => onWatch(instrumentId)}
        // ROUND-3 item 6: focus-visible ring added — the toolbar buttons are
        // keyboard-reachable via Tab once visible, so they need the shared
        // --ring treatment like every other screener control.
        className="h-5 px-1.5 flex items-center gap-0.5 text-[10px] font-mono text-muted-foreground hover:text-foreground bg-card/90 border border-border/60 rounded-[2px] hover:border-border transition-colors backdrop-blur-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <BookmarkPlus className="h-2.5 w-2.5 shrink-0" aria-hidden strokeWidth={1.5} />
        Watch
      </button>

      <button
        type="button"
        aria-label={`Create alert for ${ticker}`}
        onClick={() => onAlert(instrumentId)}
        // ROUND-3 item 6: focus-visible ring added — the toolbar buttons are
        // keyboard-reachable via Tab once visible, so they need the shared
        // --ring treatment like every other screener control.
        className="h-5 px-1.5 flex items-center gap-0.5 text-[10px] font-mono text-muted-foreground hover:text-foreground bg-card/90 border border-border/60 rounded-[2px] hover:border-border transition-colors backdrop-blur-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <Bell className="h-2.5 w-2.5 shrink-0" aria-hidden strokeWidth={1.5} />
        Alert
      </button>

      <button
        type="button"
        aria-label={`Add ${ticker} to compare set`}
        onClick={() => onCompare(ticker)}
        // ROUND-3 item 6: focus-visible ring added — the toolbar buttons are
        // keyboard-reachable via Tab once visible, so they need the shared
        // --ring treatment like every other screener control.
        className="h-5 px-1.5 flex items-center gap-0.5 text-[10px] font-mono text-muted-foreground hover:text-foreground bg-card/90 border border-border/60 rounded-[2px] hover:border-border transition-colors backdrop-blur-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <GitCompare className="h-2.5 w-2.5 shrink-0" aria-hidden strokeWidth={1.5} />
        Compare
      </button>
    </div>
  );
}
