/**
 * components/screener/LoadMoreBar.tsx — Sticky bottom "Load N more" bar
 * (PRD-0089 Wave I-A · Block A · T-IA-02)
 *
 * WHY THIS EXISTS:
 *   The screener page used to inline this paginator block (~20 LOC) at the
 *   bottom of `page.tsx`. Extracting it lets:
 *     1. The Workspace screener panel reuse the exact same load-more chrome
 *        without copy-pasting the count formatting + disabled-state logic.
 *     2. The count math (`accumulatorCount / total`) be unit-tested in
 *        isolation without standing up the full screener page query.
 *     3. `page.tsx` shed ~20 LOC, contributing to the §5 target of dropping
 *        the page LOC by ~100 across T-IA-02 + T-IA-03 + T-IA-09.
 *
 * VISUAL CONTRACT (per design 08-screener.md + previous inline block):
 *   - Row height: `h-6` (24 px). Sticky to viewport bottom via `sticky bottom-0`.
 *   - `border-t border-border bg-card`.
 *   - Left half: `[Load N more]` button. Disabled when `!canLoadMore || isFetching`.
 *   - Centre: `{accumulatorCount} of {total} loaded` — tabular-nums, mono, 10px.
 *   - Right hint: `⌘K · / Search · F Filter` — small mono hotkey reminder.
 *   - When fetching, the button copy flips to "Loading…" and `aria-busy=true`.
 *
 * WHO USES IT:
 *   - `app/(app)/screener/page.tsx` (mounted under the AG-Grid table).
 *   - Future: Workspace screener panel.
 *
 * DESIGN REF: docs/designs/0089/08-screener.md §4.1 Row 5
 * PLAN REF:   docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-02
 */

"use client";
// WHY "use client": uses an onClick handler. No SSR-only logic.

import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface LoadMoreBarProps {
  /**
   * Whether a "Load more" click is currently allowed. False when there is
   * nothing left to load, when an error is pending, or when the parent has
   * disabled pagination. Distinct from `isFetching` so the bar can be
   * disabled without flipping to the "Loading…" copy.
   */
  canLoadMore: boolean;
  /** True while a paginated fetch is in-flight. Drives the button busy state. */
  isFetching: boolean;
  /** Count of rows currently loaded into the accumulator (post-merge). */
  accumulatorCount: number;
  /** Server-reported total result count. */
  total: number;
  /** How many rows the next click will fetch (typically PAGE_SIZE or `remaining`). */
  nextBatchSize: number;
  /** Fires when the user clicks the button. */
  onLoadMore: () => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export function LoadMoreBar({
  canLoadMore,
  isFetching,
  accumulatorCount,
  total,
  nextBatchSize,
  onLoadMore,
}: LoadMoreBarProps) {
  // WHY compute `disabled` once: prevents accidental drift between the
  // `disabled` HTML attribute and the visual `disabled:` Tailwind classes.
  const disabled = !canLoadMore || isFetching;

  return (
    // WHY sticky-bottom (not absolute / fixed): the AG-Grid container above is
    // a scroll viewport with `overflow-hidden`; sticky keeps the bar pinned to
    // the bottom of the scroll container without breaking out of the page
    // layout grid the way `fixed` would.
    <div className="sticky bottom-0 z-10 flex h-6 shrink-0 items-center justify-between border-t border-border bg-card px-3">
      {/* ── Load button ───────────────────────────────────────────────── */}
      <button
        type="button"
        aria-label={isFetching ? "Loading more results" : `Load ${nextBatchSize} more results`}
        aria-busy={isFetching}
        disabled={disabled}
        onClick={onLoadMore}
        className={cn(
          // 22px tall fits inside the 24px row with 1px of breathing room top
          // and bottom. text-[10px] (not text-xs) per Terminal-Dark scope rule.
          "h-[22px] px-3 text-[10px] font-mono uppercase tracking-[0.06em] rounded-[2px] border transition-colors",
          "bg-background border-border text-muted-foreground",
          "hover:not-[:disabled]:text-foreground hover:not-[:disabled]:border-primary/60",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        {isFetching ? "Loading…" : `Load ${nextBatchSize} more`}
      </button>

      {/* ── Count readout ─────────────────────────────────────────────── */}
      {/* WHY aria-live=polite: the count updates after each pagination merge;
       *  screen-reader users hear "120 of 1024 loaded" without trapping
       *  focus or interrupting their reading flow. */}
      <span
        className="font-mono text-[10px] tabular-nums uppercase tracking-[0.06em] text-muted-foreground"
        aria-live="polite"
      >
        {accumulatorCount.toLocaleString()} of {total.toLocaleString()} loaded
      </span>

      {/* ── Hotkey hint (right-aligned) ───────────────────────────────── */}
      {/* WHY a static hint (not a live-updating overlay): the three chords
       *  are page-scoped and stable. Spinning up a hotkey-discovery overlay
       *  for an always-visible 36-character string would be overkill. */}
      <span
        className="font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/70 shrink-0"
        aria-hidden
      >
        ⌘K · / Search · F Filter
      </span>
    </div>
  );
}
