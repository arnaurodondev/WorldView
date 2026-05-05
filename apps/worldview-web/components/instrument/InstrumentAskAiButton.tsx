/**
 * components/instrument/InstrumentAskAiButton.tsx — floating Ask-AI for an
 * instrument page (PLAN-0050 T-A-1-04).
 *
 * WHY THIS EXISTS: when a trader is reading an instrument's overview, the
 * questions they want to ask the assistant are nearly always *about that
 * instrument* — "is the dividend safe?", "what does the bond market signal
 * here?", "explain this margin trend". A generic /chat link costs them the
 * cognitive overhead of re-entering the ticker context every time. A
 * floating button bottom-right on the instrument page mirrors Bloomberg's
 * MOSB ("Most Often Selected Bullets") affordance: same place on every
 * instrument, always one click away, always pre-loaded with the page
 * context so the user can just type the question.
 *
 * WHY a separate component (not the shell AskAiButton): the shell button
 * is a generic trigger that opens an empty assistant. The instrument
 * variant adds page context (ticker + price + last 30d OHLCV summary +
 * fundamentals snapshot + brief headline) to the system prompt so the
 * model can answer "is this expensive?" without the user having to spell
 * out "I am looking at AAPL". That context-stitching belongs at the page
 * boundary that owns the data — the shell button cannot see it.
 *
 * WHY bottom-right (not bottom-center, not the FAB pattern): the FAB
 * pattern (Material Design floating action button) is over-loud for a
 * data terminal — it commands attention as if it were the *primary* page
 * action, which is wrong when the primary action is "read the chart".
 * The bottom-right corner is conventional for inline help/assist (Intercom,
 * Crisp, Bloomberg's BHELP) — present but quiet. Amber tint flags it as
 * AI-related so users immediately know what it is.
 *
 * WHY render the AskAiPanel locally (not reuse the shell-level mount):
 * the floating button on the instrument page is page-scoped — the panel
 * should disappear when the user navigates away. Mounting our own panel
 * instance with a local context-pinned greeting is simpler than threading
 * page context up to the shell. Both panels share the same SSE backend so
 * there is no cost beyond rendering.
 */

"use client";
// WHY "use client": local open/close state + AskAiPanel (which needs the
// browser EventSource API).

import { useCallback, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { AskAiPanel } from "@/components/shell/AskAiPanel";
import type { Fundamentals, OHLCVBar } from "@/types/api";

interface InstrumentAskAiButtonProps {
  /** Display ticker (e.g. "AAPL") — used in the contextual greeting line. */
  ticker: string;
  /** Latest known price — feeds the contextual greeting and is part of model prompt. */
  currentPrice?: number | null;
  /** Last ~30d of OHLCV bars — used to summarise recent price action in context. */
  recentBars?: OHLCVBar[];
  /** Fundamentals snapshot — used to seed the assistant with valuation context. */
  fundamentals?: Fundamentals | null;
  /** Brief one-line summary text — if available from the morning brief, surface it. */
  briefSummary?: string | null;
}

export function InstrumentAskAiButton({
  ticker,
  currentPrice,
  // recentBars kept in props interface for API stability; not used directly here —
  // PLAN-0071 P2A-4 passes structured context via AskAiPanel's ticker/price/fundamentals props.
  recentBars: _recentBars,
  fundamentals,
  briefSummary,
}: InstrumentAskAiButtonProps) {
  const [open, setOpen] = useState(false);
  // F-QA2-04 fix: mirror the shell-trigger focus-restore pattern so closing
  // the page-scoped panel (Escape, X, "open full chat") returns focus to
  // the floating trigger — WCAG 2.4.3.
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const handleClose = useCallback(() => {
    setOpen(false);
    // RAF lets React commit the trigger remount before focus() is attempted.
    requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);


  return (
    <>
      {/*
        Floating trigger. Why fixed bottom-6 right-6 (24px each side):
        - 16px (the AskAiPanel's bottom-4 right-4) would overlap the panel
          when open. 24px keeps the trigger visible above the panel header
          when both are mounted (and remains a comfortable thumb target on
          tablet sizes).
        - z-40: below the panel (z-50) so when both are open the panel
          renders on top, and below FlashOverlay (z-[9999]).
      */}
      {!open && (
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen(true)}
          // F-QA-12: bottom-10 (40px) places the button above the 24px
          // StatusBar with comfortable clearance. The previous bottom-6
          // placed the bottom edge of a 32px button flush with the StatusBar
          // top edge, intercepting clicks on status connectors at the right
          // edge of the bar.
          // PLAN-0059 W0 F-VISUAL-022: --accent-ai violet (was amber-*)
          className="fixed bottom-10 right-6 z-40 flex items-center gap-1.5 rounded-[2px] border border-[hsl(var(--accent-ai)/0.40)] bg-[hsl(var(--accent-ai)/0.90)] px-3 py-2 text-xs font-semibold text-white shadow-lg transition-colors hover:bg-[hsl(var(--accent-ai))]"
          aria-label={`Ask AI about ${ticker}`}
          title={`Ask AI about ${ticker}`}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          Ask AI · {ticker}
        </button>
      )}

      {open && (
        <AskAiPanel
          onClose={handleClose}
          // PLAN-0071 P2A-4: pass structured props so AskAiPanel.buildSystemContext()
          // includes system_context in the POST body. This is what makes the backend
          // model context-aware without the user re-stating the ticker.
          // contextHint still surfaces the display strip for UX continuity.
          ticker={ticker}
          price={currentPrice ?? undefined}
          fundamentals={
            fundamentals
              ? { pe: fundamentals.pe_ratio ?? null, marketCap: fundamentals.market_cap ?? null }
              : undefined
          }
          contextHint={briefSummary ? `Brief: ${briefSummary}` : undefined}
        />
      )}
    </>
  );
}
