/**
 * components/shell/AskAiButton.tsx — TopBar trigger for the floating AskAiPanel
 *
 * WHY THIS EXISTS (PLAN-0050 T-A-1-03): the AskAiPanel was already built
 * but never wired into the shell — there was no way for a user to actually
 * open it. The audit (2026-04-28 §F-D-026) flagged that the chat assistant
 * is buried inside /chat, forcing a full route change to ask one quick
 * question. A persistent TopBar trigger keeps the assistant one click away
 * from every page in the (app)/ route group, matching the Bloomberg
 * convention of a permanent "Help/Search" rail entry that never moves.
 *
 * WHY a separate component (not inline JSX in TopBar): the trigger's only
 * visual concern is "amber-tinted icon + accessible label". Hosting it in
 * its own file keeps TopBar.tsx focused on the layout contract and lets
 * us test the click → onOpen contract in isolation.
 *
 * WHY amber (not primary yellow): per the Midnight Pro palette decision,
 * primary yellow (#FFD60A) is reserved for data CTAs (Buy, Drill-down,
 * Refresh). Amber-500 marks AI-interactive surfaces app-wide so users
 * recognise "this is the AI" instantly — the same token used inside the
 * AskAiPanel header (Bot icon container) and the InstrumentAskAiButton
 * floater. Consistency here means the user never has to wonder whether a
 * yellow-ish thing is data or AI.
 *
 * WHY not a popover-component-with-baked-in-input: the open contract is
 * controlled by the parent layout so we can render the panel at the
 * layout root (the panel is fixed-positioned and must escape any
 * overflow-hidden container deeper in the shell). The button's only job
 * is to call `onOpen` — keeping it dumb makes E2E coverage trivial.
 *
 * WHO USES IT: components/shell/TopBar.tsx
 * DATA SOURCE: none (it's a pure trigger)
 */

"use client";
// WHY "use client": the component is interactive (onClick handler) and
// imports a Lucide icon component, both of which require client rendering
// in App Router.

import { forwardRef } from "react";
import { Sparkles } from "lucide-react";

interface AskAiButtonProps {
  /** Called when the user clicks the button. The parent owns the panel-open state. */
  onOpen: () => void;
  /** True while the panel is currently shown — toggles the visual pressed state. */
  isOpen?: boolean;
}

/**
 * AskAiButton — small icon-with-label TopBar control.
 *
 * Visual: 24×24 amber-tinted square housing the Sparkles icon + the literal
 * word "AI". Sized to match the Bell button's weight so the rail keeps a
 * consistent rhythm; we avoid an oversized CTA so this doesn't compete
 * visually with the portfolio value (which is the rail's single most
 * important number).
 */
// F-QA-05: forwardRef so the layout can refocus this trigger when the panel
// closes — a WCAG 2.4.3 requirement for transient overlays. Without the ref
// the parent has no handle to restore focus to.
export const AskAiButton = forwardRef<HTMLButtonElement, AskAiButtonProps>(
  function AskAiButton({ onOpen, isOpen = false }, ref) {
    return (
      <button
        ref={ref}
        type="button"
        onClick={onOpen}
        // WHY rounded-[2px]: design system mandates 2px radius across the shell.
        // WHY ring + bg shift on isOpen: the floating panel is fixed bottom-right
        // so users lose the visual link back to the trigger; a faint ring keeps
        // the button visually "lit" while the panel is open.
        // PLAN-0059 W0 F-VISUAL-022: --accent-ai violet (was amber-* defaults)
        className={`flex h-6 items-center gap-1 rounded-[2px] border border-[hsl(var(--accent-ai)/0.30)] bg-[hsl(var(--accent-ai)/0.15)] px-1.5 text-[11px] font-semibold text-[hsl(var(--accent-ai))] transition-colors hover:bg-[hsl(var(--accent-ai)/0.25)] ${
          isOpen ? "ring-1 ring-[hsl(var(--accent-ai)/0.60)]" : ""
        }`}
        aria-label="Open AI assistant"
        aria-pressed={isOpen}
        // F-QA-19: dropped the "coming soon" copy — the keyboard shortcut is
        // not yet wired so advertising it was untruthful. We will reinstate
        // the hint when the global ⌘K handler ships.
        title="Ask AI"
      >
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        AI
      </button>
    );
  },
);
