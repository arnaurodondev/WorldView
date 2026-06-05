/**
 * features/portfolio/components/HoldingDetailPanel.tsx — per-holding slide-over
 * (PRD-0089 SA-B)
 *
 * WHY THIS EXISTS: The holdings table gives traders a portfolio-level view of all
 * positions. This panel adds a second level of granularity: click any row to see
 * the FIFO tax lots, contribution stats, recent transactions, and news for that
 * specific holding without leaving the portfolio page.
 *
 * DESIGN DECISIONS:
 * - Fixed 440px right-anchored panel: avoids colliding with the main content at
 *   typical laptop widths (1366px+). The portfolio table occupies the left ~920px;
 *   440px on the right keeps the panel inside the viewport with no scroll.
 * - aria-modal="false": the rest of the page remains interactive (drawer, not
 *   modal). The user can scroll the table while the panel is open.
 * - No backdrop / overlay: the terminal aesthetic (Bloomberg) keeps the panel
 *   visually separated by the border-l alone. An overlay would occlude the table
 *   the user needs to reference.
 * - Escape key → close: keyboard accessibility convention for drawers.
 * - translate-x-full when closed (not display:none): the DOM node stays mounted
 *   so TanStack Query prefetches inside it while it's "hidden" — data is ready
 *   the instant it slides into view.
 *
 * WHO USES IT: HoldingsTab (wired in step F)
 * DESIGN REFERENCE: PRD-0089 SA-B §E
 */

"use client";
// WHY "use client": useEffect, useRouter, and composition of useQuery-based
// child components all require a browser context.

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { HoldingRealizedRow } from "@/components/portfolio/HoldingRealizedRow";
import { HoldingContributionStat } from "@/components/portfolio/HoldingContributionStat";
import { HoldingLotsPanel } from "@/components/portfolio/HoldingLotsPanel";
import { HoldingInstrumentTxList } from "@/components/portfolio/HoldingInstrumentTxList";
import { HoldingNewsList } from "@/components/portfolio/HoldingNewsList";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Holding } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface HoldingDetailPanelProps {
  portfolioId: string;
  /**
   * The holding to display. When null the panel is invisible (translate-x-full)
   * but remains mounted so TanStack Query keeps its cache warm.
   *
   * WHY use the full Holding type (not a minimal sub-type): the caller
   * (HoldingsTab) already has enriched Holding[] available. Accepting the
   * full type avoids a separate lookup and keeps the prop contract simple.
   */
  holding: Holding | null;
  /** Called when the panel should close (Esc key or ✕ button). */
  onClose: () => void;
  /** Portfolio period (e.g. "1M", "3M") — forwarded to HoldingContributionStat. */
  period: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HoldingDetailPanel({
  portfolioId,
  holding,
  onClose,
  period,
}: HoldingDetailPanelProps) {
  const router = useRouter();

  // ── Keyboard listener ─────────────────────────────────────────────────────
  // WHY useEffect + window.addEventListener (not onKeyDown on the panel div):
  // the panel div is not focused when it opens — the user's focus is on the
  // row they clicked. Listening at the window level means Escape works
  // regardless of where focus sits after the click.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    // WHY return cleanup: if the component unmounts while the listener is
    // registered (e.g., portfolio page unmount) we'd leak the handler and
    // the next Escape key press anywhere in the app would error.
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // ── Position summary helpers ──────────────────────────────────────────────

  /**
   * Current market value of the holding.
   * WHY current_price × quantity (not a dedicated field): Holding.current_price
   * is populated by the parent from live batch quotes. Multiplying client-side
   * avoids a round-trip and matches how the KPI strip computes total value.
   */
  const currentValue =
    holding && holding.current_price != null
      ? holding.current_price * holding.quantity
      : null;

  return (
    // WHY fixed inset-y-0 right-0: right-anchored slide-over that covers full
    // viewport height. z-20 sits above the table (z-10) but below modals (z-50).
    <aside
      role="dialog"
      // WHY aria-modal="false": the rest of the page is still interactive.
      // Bloomberg-style drawers don't trap focus — the trader can reference
      // the table while the panel is open.
      aria-modal="false"
      aria-label={
        holding ? `Holding detail for ${holding.ticker}` : "Holding detail"
      }
      className={cn(
        // Layout: full-height right strip
        "fixed inset-y-0 right-0 w-[440px] z-20",
        // Visual: card background with left border separator
        "bg-card border-l border-border",
        // WHY flex flex-col: header must stay fixed at top while content scrolls
        "flex flex-col",
        // Slide animation: translate out to the right when hidden
        "transition-[transform] duration-[120ms] ease-out",
        // WHY translate-x-full (not visibility:hidden): the DOM stays mounted
        // so TanStack Query keeps its cache alive while the panel is hidden.
        holding !== null ? "translate-x-0" : "translate-x-full",
      )}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      {/* WHY sticky header: the content area scrolls; the close button should
          always be accessible without scrolling back to the top. */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-card/80 backdrop-blur-sm shrink-0">
        <div className="flex items-baseline gap-2 min-w-0">
          {/* Ticker — primary identifier, monospace for terminal aesthetic */}
          <span className="text-[13px] font-mono font-semibold text-primary">
            {holding?.ticker ?? "—"}
          </span>
          {/* Full company name — subdued, truncated when long */}
          <span className="truncate text-[11px] text-muted-foreground">
            {holding?.name}
          </span>
        </div>

        {/* Close button — ✕ icon */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close holding detail"
          className="ml-2 shrink-0 rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {/* WHY text symbol not SVG: SVG import adds a dep; × is universally
              legible at this font size and matches the terminal aesthetic. */}
          <span aria-hidden className="text-[14px] leading-none">✕</span>
        </button>
      </div>

      {/* ── Scrollable content ──────────────────────────────────────────────── */}
      {/* WHY overflow-y-auto (not scroll): auto only shows scrollbar when
          needed. scroll always shows it, adding visual noise on macOS.       */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* ── Section 1: Position summary ──────────────────────────────────── */}
        {/* Shows current market value + total P&L from the enriched holding.  */}
        <div className="flex items-center gap-4 px-3 py-2 border-b border-border">
          <div>
            <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Value
            </div>
            <div className="font-mono text-[12px] tabular-nums text-foreground">
              {formatPrice(currentValue)}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Qty
            </div>
            <div className="font-mono text-[12px] tabular-nums text-foreground">
              {holding?.quantity.toLocaleString("en-US", { maximumFractionDigits: 4 }) ?? "—"}
            </div>
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Unrealised
            </div>
            <div
              className={cn(
                "font-mono text-[12px] tabular-nums",
                holding?.unrealised_pnl == null
                  ? "text-muted-foreground"
                  : holding.unrealised_pnl >= 0
                    ? "text-positive"
                    : "text-negative",
              )}
            >
              {holding?.unrealised_pnl != null
                ? `${holding.unrealised_pnl >= 0 ? "+" : ""}${formatPrice(holding.unrealised_pnl)}`
                : "—"}
              {holding?.unrealised_pnl_pct != null && (
                <span className="ml-1 text-[10px] text-muted-foreground">
                  ({formatPercent(holding.unrealised_pnl_pct)})
                </span>
              )}
            </div>
          </div>
        </div>

        {/* ── Section 2: Realized P&L (ST/LT split) ────────────────────────── */}
        {/* Only queries when holding is non-null — the key uses portfolioId  */}
        {/* so a single response covers all instruments without re-fetching.  */}
        {holding && (
          <div className="border-b border-border">
            <HoldingRealizedRow
              portfolioId={portfolioId}
              instrumentId={holding.instrument_id}
            />
          </div>
        )}

        {/* ── Section 3: Contribution stat (bps + weight) ───────────────────── */}
        {/* Client-side computation from cached holdings + value-history.       */}
        {holding && (
          <div className="border-b border-border">
            <HoldingContributionStat
              portfolioId={portfolioId}
              instrumentId={holding.instrument_id}
              period={period}
            />
          </div>
        )}

        {/* ── Section 4: FIFO tax lots ──────────────────────────────────────── */}
        {/* variant="narrow" drops the "Days Held" column to fit the 440px panel. */}
        {/* WHY conditional on holding: HoldingLotsPanel requires portfolioId    */}
        {/* and an instrument to select; null holding = nothing to show.         */}
        {holding && (
          <div className="border-b border-border">
            {/* Section header — matches the other section labels for consistency */}
            <div className="px-3 pt-2 pb-1">
              <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Tax Lots
              </span>
            </div>
            <HoldingLotsPanel
              portfolioId={portfolioId}
              // WHY an array with only this holding: HoldingLotsPanel accepts
              // a holdings[] and renders a ticker dropdown. Passing a single-
              // element array removes the dropdown (effectively pre-selects
              // the holding) and keeps the component contract unchanged.
              holdings={[holding]}
              // WHY empty quotes: the narrow panel doesn't need live prices
              // to render lots — lot data (unrealised_pnl) comes from the API.
              // currentPrice from the quotes map is passed as undefined here;
              // HoldingLotsPanel uses it as an optional enrichment.
              quotes={{}}
            />
          </div>
        )}

        {/* ── Section 5: Recent transactions for this instrument ────────────── */}
        {holding && (
          <div className="border-b border-border">
            <div className="px-3 pt-2 pb-1">
              <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                Transactions
              </span>
            </div>
            <HoldingInstrumentTxList
              portfolioId={portfolioId}
              instrumentId={holding.instrument_id}
              limit={5}
            />
          </div>
        )}

        {/* ── Section 6: Recent news ────────────────────────────────────────── */}
        {/* Uses instrument_id as the entity_id (unified namespace per PRD-0089 F2) */}
        {holding && (
          <div className="border-b border-border">
            <div className="px-3 pt-2 pb-1">
              <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                News
              </span>
            </div>
            <HoldingNewsList
              instrumentId={holding.instrument_id}
              limit={5}
            />
          </div>
        )}

        {/* ── Bottom CTA ───────────────────────────────────────────────────── */}
        {/* Navigates to the full instrument detail page for deeper analysis.  */}
        {holding && (
          <div className="py-1">
            <button
              type="button"
              onClick={() => router.push(`/instruments/${encodeURIComponent(holding.ticker)}`)}
              disabled={!holding.ticker}
              className="w-full text-[11px] text-muted-foreground hover:text-foreground transition-colors py-2 text-center font-mono disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Open Instrument →
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
